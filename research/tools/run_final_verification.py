from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from idr.phase12 import verify_release  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify and package the final SIH26168 Android release without training.")
    parser.add_argument("--apk", type=Path, default=Path("android/app/build/outputs/apk/debug/app-debug.apk"))
    parser.add_argument("--kotlin-tests", type=int, required=True)
    parser.add_argument("--python-tests", type=int, required=True)
    parser.add_argument("--output", type=Path, default=Path("results/phase12"))
    args = parser.parse_args()
    root = ROOT
    result = verify_release(root, root / args.apk, args.kotlin_tests, args.python_tests, root / args.output)
    print(json.dumps(result.verification, indent=2))
    return 0 if result.verification["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
