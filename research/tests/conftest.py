"""Make the repository's src layout importable for the documented pytest command."""

from __future__ import annotations

import sys
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))
