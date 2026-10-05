"""Validate and summarize a local Phase 9 Android recording."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from idr.phase9 import load_android_session  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path)
    args = parser.parse_args()
    session = load_android_session(args.session)
    print(json.dumps({
        "session_id": session.session_id,
        "runtime_samples": len(session.runtime),
        "raw_imu_samples": len(session.raw_imu),
        "raw_physical_gnss_samples": len(session.raw_physical_gnss),
        "missing_sensors": session.missing_sensors,
        "achieved_rates_hz": session.achieved_rates_hz(),
        "blackout_runtime_samples": int(session.runtime["simulated_blackout"].sum()),
        "gnss_diagnostics": session.metadata.get("gnss_diagnostics"),
    }, indent=2))


if __name__ == "__main__":
    main()
