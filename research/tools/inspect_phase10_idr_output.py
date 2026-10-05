"""Validate and summarize an exported Phase 10 Android IDR session."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from idr.phase10 import load_android_idr_output  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path)
    args = parser.parse_args()
    frame = load_android_idr_output(args.session)
    print(json.dumps({
        "samples": len(frame),
        "duration_seconds": float(frame["elapsed_seconds"].iloc[-1] - frame["elapsed_seconds"].iloc[0]),
        "localization_state_counts": frame["localization_state"].value_counts().sort_index().to_dict(),
        "ml_state_counts": frame["ml_state"].value_counts().sort_index().to_dict(),
        "maximum_dr_duration_seconds": float(frame["dr_duration_seconds"].max()),
        "maximum_uncertainty_m": float(frame["horizontal_uncertainty_m"].max()),
        "final_local_east_m": float(frame["local_east_m"].iloc[-1]),
        "final_local_north_m": float(frame["local_north_m"].iloc[-1]),
        "reported_engine_average_ms": float(frame["engine_average_ms"].iloc[-1]),
        "reported_engine_p95_ms": float(frame["engine_p95_ms"].iloc[-1]),
    }, indent=2))


if __name__ == "__main__":
    main()
