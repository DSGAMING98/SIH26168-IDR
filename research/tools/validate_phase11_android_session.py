"""Validate an exported Phase 11 Android field-test session offline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from idr.phase11 import validate_android_session


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path, help="Exported Android session directory")
    parser.add_argument("--reference", type=Path, help="Optional independent CSV or GPX reference")
    parser.add_argument("--output", type=Path, help="External output directory (default: beside session data)")
    args = parser.parse_args()
    result = validate_android_session(args.session, reference_path=args.reference, output_directory=args.output)
    print(json.dumps(result.to_dict(), indent=2))
    if result.output_directory:
        print(f"Report: {result.output_directory}")
    return 0 if result.evaluable else 2


if __name__ == "__main__":
    raise SystemExit(main())
