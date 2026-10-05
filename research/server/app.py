"""Local-first telemetry receiver and read-only Command Center.

Run one worker: memory is intentionally process-local. This module has no engine
imports and cannot issue commands to a phone. Bind LAN only with explicit --lan.
"""
import asyncio
from contextlib import asynccontextmanager, suppress
import ipaddress
from pathlib import Path
from urllib.parse import urlsplit
import uuid

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .schema import Telemetry
from .state import Hub, Limits, RejectedTelemetry
from .geomesh import GeoFenceCreate, GeoMeshStore, GeoMeshVote

STATIC = Path(__file__).parent / "static"


def allowed_origin(websocket: WebSocket) -> bool:
    """Native phones omit Origin; browsers must use this server's exact origin.

    Restrict browser-facing hostnames to localhost or private LAN IPs as a basic
    DNS-rebinding guard. This is a trusted-LAN observer, not internet auth.
    """
    host = websocket.headers.get("host", "")
    try:
        parsed_host = urlsplit("http://" + host).hostname
        private = parsed_host in {"localhost", "testserver"} or ipaddress.ip_address(parsed_host).is_private
    except (ValueError, TypeError):
        private = False
    if not private:
        return False
    origin = websocket.headers.get("origin")
    if origin is None:
        return True
    try:
        parsed = urlsplit(origin)
        return parsed.scheme in {"http", "https"} and parsed.netloc == host and not parsed.path and not parsed.query and not parsed.fragment
    except ValueError:
        return False


async def guarded_send(websocket: WebSocket, data: dict, seconds: float):
    await asyncio.wait_for(websocket.send_json(data), timeout=seconds)


def create_app(limits: Limits = Limits(), geomesh_store: GeoMeshStore | None = None) -> FastAPI:
    hub = Hub(limits)
    geomesh = geomesh_store or GeoMeshStore()

    @asynccontextmanager
    async def lifespan(_app):
        async def heartbeat():
            while True:
                await asyncio.sleep(1)
                hub.cleanup()
                hub.broadcast({"type": "status", "sessions": [hub.summary(s) for s in hub.sessions.values()]})
        task = asyncio.create_task(heartbeat())
        yield
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        hub.sessions.clear()
        hub.viewers.clear()

    app = FastAPI(title="NavGhost Command Center", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.hub = hub
    app.state.geomesh = geomesh

    @app.middleware("http")
    async def privacy_headers(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https://tile.openstreetmap.org; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        return response

    @app.get("/")
    async def dashboard():
        return FileResponse(STATIC / "index.html")

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "navghost-command-center", "schema_version": 1}

    @app.get("/api/status")
    async def status():
        return hub.status()

    @app.get("/api/geomesh/health")
    async def geomesh_health():
        return geomesh.health()

    @app.post("/api/geomesh/geofences", status_code=201)
    async def create_geofence(item: GeoFenceCreate):
        try: return geomesh.create(item)
        except ValueError as error: raise HTTPException(422, str(error)) from error

    @app.get("/api/geomesh/geofences")
    async def nearby_geofences(min_lat: float = Query(ge=-90, le=90), max_lat: float = Query(ge=-90, le=90),
                               min_lon: float = Query(ge=-180, le=180), max_lon: float = Query(ge=-180, le=180)):
        if min_lat > max_lat or min_lon > max_lon: raise HTTPException(422, "invalid_bounds")
        return {"geofences": geomesh.nearby(min_lat, max_lat, min_lon, max_lon)}

    @app.post("/api/geomesh/geofences/{zone_id}/confirmation")
    async def confirm_geofence(zone_id: str, vote: GeoMeshVote):
        result = geomesh.vote(zone_id, vote.vote)
        if result is None: raise HTTPException(404, "geofence_not_found")
        return result

    @app.post("/api/geomesh/geofences/{zone_id}/denial")
    async def deny_geofence(zone_id: str):
        result = geomesh.vote(zone_id, "NO_LONGER_PRESENT")
        if result is None: raise HTTPException(404, "geofence_not_found")
        return result

    @app.websocket("/ws/telemetry")
    async def telemetry_socket(websocket: WebSocket):
        if not allowed_origin(websocket) or len(hub.producers) >= limits.max_sessions:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        owner, bound_session, errors = uuid.uuid4().hex, None, 0
        hub.producers.add(owner)
        try:
            while True:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=limits.receive_timeout_s)
                if len(raw.encode("utf-8")) > limits.max_message_bytes:
                    await websocket.close(code=1009)
                    break
                try:
                    telemetry = Telemetry.model_validate_json(raw)
                    if bound_session is not None and bound_session != telemetry.session_id:
                        raise RejectedTelemetry("session_changed")
                    hub.accept(telemetry, owner)
                    bound_session = telemetry.session_id
                except (ValidationError, RejectedTelemetry) as error:
                    hub.rejected += 1
                    errors += 1
                    code = str(error) if isinstance(error, RejectedTelemetry) else "invalid_telemetry"
                    # Never echo rejected values or Pydantic's input/context details.
                    await guarded_send(websocket, {"type": "error", "code": code,
                        "detail": "Expected the NavGhost version 1 allowlisted snapshot schema."}, limits.send_timeout_s)
                    if errors >= 5:
                        await websocket.close(code=1008)
                        break
                    continue
                await guarded_send(websocket, {"type": "accepted", "sequence": telemetry.sequence}, limits.send_timeout_s)
        except (WebSocketDisconnect, asyncio.TimeoutError, RuntimeError, KeyError):
            pass
        finally:
            hub.disconnect(owner)
            with suppress(RuntimeError, WebSocketDisconnect):
                await websocket.close()

    @app.websocket("/ws/dashboard")
    async def dashboard_socket(websocket: WebSocket):
        if not allowed_origin(websocket):
            await websocket.close(code=1008)
            return
        try:
            # Send the initial snapshot directly. If it were placed in the one-slot coalescing
            # queue, the one-second heartbeat could replace it before a newly accepted socket had
            # a chance to read it.
            queue = hub.subscribe(initial_snapshot=False)
        except RejectedTelemetry:
            await websocket.close(code=1013)
            return
        try:
            await websocket.accept()
            await guarded_send(websocket, hub.snapshot(), limits.send_timeout_s)
        except (WebSocketDisconnect, RuntimeError):
            hub.viewers.discard(queue)
            return

        async def sender():
            while True:
                await guarded_send(websocket, await queue.get(), limits.send_timeout_s)

        async def receiver():
            # Receive solely to notice disconnects; no control commands exist.
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    return
                await websocket.close(code=1008)
                return

        tasks = [asyncio.create_task(sender()), asyncio.create_task(receiver())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            # Remove the subscription before awaiting cancelled child tasks. The endpoint
            # itself can be cancelled while a client is closing; deferring this discard
            # until after gather would then leak a dead viewer in the hub.
            hub.viewers.discard(queue)
            for task in tasks:
                task.cancel()
            with suppress(asyncio.CancelledError):
                await asyncio.gather(*tasks, return_exceptions=True)
            with suppress(RuntimeError, WebSocketDisconnect):
                await websocket.close()

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()
