"""Finite loopback-only protocol smoke stream. SYNTHETIC DEMO, never phone validation."""
import argparse
import asyncio
from datetime import datetime, timezone
import math
import time
import uuid

from .schema import Telemetry

STATES = ("GNSS_ACTIVE", "GNSS_DEGRADED", "IDR_ACTIVE", "GNSS_VERIFYING", "GNSS_RECOVERING", "GNSS_ACTIVE")


def frame(sequence: int, session_id: str, duration_s: float = 30.0) -> Telemetry:
    elapsed = sequence / 5.0
    phase = min(5, int(elapsed / max(duration_s / 6, 0.2)))
    state = STATES[phase]
    # Illustrative local geometry only. No location, real sensor rates, or device metrics invented.
    angle = elapsed / 22.0
    return Telemetry.model_validate({
        "schema_version": 1, "session_id": session_id, "sequence": sequence,
        "timestamp_ns": str(time.monotonic_ns()),
        "wall_time_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mode": "DEMO", "recording": False,
        "estimated_position": {"local_east_m": elapsed * 5.0, "local_north_m": 30.0 * math.sin(angle)},
        "motion": {"speed_mps": 5.0, "speed_kmh": 18.0, "heading_deg": 75.0 + 15.0 * math.sin(angle)},
        "navigation": {"localization_state": state,
            "gnss_state": "SIMULATED_BLACKOUT" if phase in (1, 2) else "FRESH",
            "dr_duration_s": max(0.0, elapsed - duration_s / 6) if phase in (1, 2, 3, 4) else 0.0,
            "uncertainty_m": 5.0 + 1.5 * max(0.0, elapsed - duration_s / 6) if phase in (1, 2) else 5.0,
            "confidence": "UNAVAILABLE", "alignment_state": "READY", "motion_state": "MOVING"},
        "ai": {"state": "UNAVAILABLE", "ml_state": "ML_UNAVAILABLE"},
        "sensors": {}, "gnss_observability": {}, "engine": {}, "device": {},
        "field_test_state": "IDLE", "map_mode": "LOCAL_ENU",
    })


async def run(port: int, seconds: float):
    from websockets.asyncio.client import connect
    session_id = "demo-" + uuid.uuid4().hex[:12]
    print("SYNTHETIC DEMO ONLY: verifies protocol/UI, not phone GNSS or estimator accuracy.", flush=True)
    async with connect(f"ws://127.0.0.1:{port}/ws/telemetry", max_queue=1, max_size=16384) as ws:
        for index in range(int(seconds * 5)):
            await ws.send(frame(index, session_id, seconds).model_dump_json())
            response = await asyncio.wait_for(ws.recv(), timeout=3)
            if '"accepted"' not in response:
                raise RuntimeError("Demo frame rejected")
            await asyncio.sleep(0.2)
    print("Synthetic stream complete. Dashboard should show PHONE OFFLINE.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--seconds", type=float, default=30)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or not 2 <= args.seconds <= 120:
        parser.error("port must be 1..65535 and duration 2..120 seconds")
    asyncio.run(run(args.port, args.seconds))


if __name__ == "__main__":
    main()
