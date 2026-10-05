#!/usr/bin/env python3
"""Inspect and validate the locally cached Phase 6 road graph."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from idr.map_matching import RoadGraph  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", default="data/map_cache/io_vnbd_s1/road_graph.json.gz")
    args = parser.parse_args()
    path = Path(args.cache)
    path = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    graph = RoadGraph.load(path)
    report = {
        "cache": str(path),
        "size_bytes": path.stat().st_size,
        "node_count": len(graph.nodes),
        "directed_edge_count": len(graph.edges),
        "road_classes": sorted({edge.road_class for edge in graph.edges}),
        "metadata": graph.metadata,
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
