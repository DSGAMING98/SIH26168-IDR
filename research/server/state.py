"""Bounded, ephemeral fan-out. There is intentionally no telemetry persistence."""
import asyncio
from collections import deque
from dataclasses import dataclass, field
import time
from typing import Callable

from .schema import Telemetry


@dataclass(frozen=True)
class Limits:
    max_sessions: int = 4
    max_viewers: int = 8
    history_points: int = 600
    history_events: int = 40
    stale_after_s: float = 3.0
    expire_after_s: float = 600.0
    max_message_bytes: int = 16384
    send_timeout_s: float = 2.0
    receive_timeout_s: float = 30.0


@dataclass
class Session:
    session_id: str
    first_received: float
    last_received: float
    owner: str | None = None
    latest: dict | None = None
    history: deque = field(default_factory=deque)
    timeline: deque = field(default_factory=deque)
    events: deque = field(default_factory=deque)
    last_sequence: int = -1
    last_timestamp_ns: int = -1


class RejectedTelemetry(ValueError):
    pass


class Hub:
    def __init__(self, limits: Limits = Limits(), clock: Callable[[], float] = time.monotonic):
        self.limits, self.clock = limits, clock
        self.sessions: dict[str, Session] = {}
        self.viewers: set[asyncio.Queue] = set()
        self.producers: set[str] = set()
        self.accepted = self.rejected = self.coalesced = 0

    def connection_status(self, session: Session) -> str:
        if session.owner is None:
            return "OFFLINE"
        return "STALE" if self.clock() - session.last_received > self.limits.stale_after_s else "CONNECTED"

    def summary(self, session: Session, history=False) -> dict:
        result = {"session_id": session.session_id, "connection": self.connection_status(session),
                  "last_update_age_s": max(0, self.clock() - session.last_received),
                  "session_duration_s": max(0, self.clock() - session.first_received),
                  "latest": session.latest, "timeline": list(session.timeline), "events": list(session.events)}
        if history:
            result["history"] = list(session.history)
        return result

    def snapshot(self) -> dict:
        return {"type": "snapshot", "sessions": [self.summary(s, history=True) for s in self.sessions.values()]}

    def status(self) -> dict:
        return {"status": "ok", "schema_version": 1, "storage": "memory_only", "sessions": len(self.sessions),
                "connected_phones": sum(s.owner is not None for s in self.sessions.values()),
                "dashboard_viewers": len(self.viewers), "accepted_frames": self.accepted,
                "rejected_frames": self.rejected, "viewer_frames_coalesced": self.coalesced}

    def subscribe(self, initial_snapshot: bool = True) -> asyncio.Queue:
        if len(self.viewers) >= self.limits.max_viewers:
            raise RejectedTelemetry("viewer_limit")
        queue = asyncio.Queue(maxsize=1)
        self.viewers.add(queue)
        if initial_snapshot:
            queue.put_nowait(self.snapshot())
        return queue

    def broadcast(self, packet: dict):
        for queue in tuple(self.viewers):
            if queue.full():
                queue.get_nowait()
                self.coalesced += 1
            queue.put_nowait(packet)

    def accept(self, telemetry: Telemetry, owner: str) -> Session:
        self.cleanup()
        now = self.clock()
        session = self.sessions.get(telemetry.session_id)
        if session is None:
            if len(self.sessions) >= self.limits.max_sessions:
                # Retain active phones; evict only the least recently seen offline session.
                offline = [s for s in self.sessions.values() if s.owner is None]
                if not offline:
                    raise RejectedTelemetry("session_limit")
                del self.sessions[min(offline, key=lambda s: s.last_received).session_id]
            session = Session(telemetry.session_id, now, now,
                              history=deque(maxlen=self.limits.history_points),
                              timeline=deque(maxlen=self.limits.history_events),
                              events=deque(maxlen=self.limits.history_events))
            self.sessions[telemetry.session_id] = session
        if session.owner is not None and session.owner != owner:
            raise RejectedTelemetry("session_owned")
        if telemetry.sequence <= session.last_sequence or int(telemetry.timestamp_ns) < session.last_timestamp_ns:
            raise RejectedTelemetry("out_of_order")
        previous = session.latest
        data = telemetry.model_dump(mode="json")
        session.owner = owner
        session.last_sequence, session.last_timestamp_ns = telemetry.sequence, int(telemetry.timestamp_ns)
        session.last_received, session.latest = now, data
        sample = {**data["estimated_position"], "state": data["navigation"]["localization_state"],
                  "heading_deg": data["motion"]["heading_deg"], "sequence": telemetry.sequence,
                  "timestamp_ns": telemetry.timestamp_ns}
        session.history.append(sample)
        event_time = {"wall_time_utc": data["wall_time_utc"], "timestamp_ns": telemetry.timestamp_ns}
        if previous is None or previous["navigation"]["localization_state"] != data["navigation"]["localization_state"]:
            transition = {**event_time, "state": data["navigation"]["localization_state"]}
            session.timeline.append(transition)
            session.events.append({**event_time, "kind": "navigation", "message": transition["state"]})
        for section, key in (("navigation", "gnss_state"), ("ai", "state")):
            current = data[section][key]
            if previous is not None and previous[section][key] != current:
                session.events.append({**event_time, "kind": section, "message": current or "UNAVAILABLE"})
        self.accepted += 1
        self.broadcast({"type": "telemetry", "session": self.summary(session), "point": sample})
        return session

    def disconnect(self, owner: str):
        self.producers.discard(owner)
        for session in self.sessions.values():
            if session.owner == owner:
                session.owner = None
        self.broadcast({"type": "status", "sessions": [self.summary(s) for s in self.sessions.values()]})

    def cleanup(self):
        expired = [sid for sid, s in self.sessions.items() if self.clock() - s.last_received > self.limits.expire_after_s]
        for sid in expired:
            del self.sessions[sid]
        return expired
