#!/usr/bin/env python3
"""Download one fixed OpenStreetMap region and build the offline S1 road cache."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from idr.map_matching.road_graph import RoadEdge, RoadGraph, RoadNode  # noqa: E402


def _resolve(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate.resolve() if candidate.is_absolute() else (ROOT / candidate).resolve()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _overpass_query(config: dict[str, Any]) -> str:
    bounds = config["bounds_wgs84"]
    bbox = ",".join(str(bounds[name]) for name in ("south", "west", "north", "east"))
    classes = "|".join(config["road_classes"])
    return (
        f'[out:json][timeout:180];way["highway"~"^({classes})$"]({bbox});'
        "out body;>;out skel qt;"
    )


def _download(config: dict[str, Any]) -> dict[str, Any]:
    payload = urllib.parse.urlencode({"data": _overpass_query(config)}).encode("utf-8")
    request = urllib.request.Request(
        config["overpass_url"],
        data=payload,
        headers={"User-Agent": "SIH26168-IDR-offline-map-cache/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=240) as response:
        return json.loads(response.read().decode("utf-8"))


def build_graph(payload: dict[str, Any], config: dict[str, Any]) -> RoadGraph:
    raw_nodes = {
        str(item["id"]): (float(item["lat"]), float(item["lon"]))
        for item in payload.get("elements", ())
        if item.get("type") == "node" and "lat" in item and "lon" in item
    }
    allowed = set(config["road_classes"])
    excluded_access = set(config.get("excluded_access_values", ()))
    edges: list[RoadEdge] = []
    used_nodes: set[str] = set()
    for way in payload.get("elements", ()):
        if way.get("type") != "way":
            continue
        tags = way.get("tags", {})
        road_class = tags.get("highway")
        if road_class not in allowed:
            continue
        if tags.get("access") in excluded_access or tags.get("vehicle") in excluded_access or tags.get("motor_vehicle") in excluded_access:
            continue
        node_ids = [str(value) for value in way.get("nodes", ())]
        if len(node_ids) < 2 or any(node_id not in raw_nodes for node_id in node_ids):
            continue
        oneway_value = str(tags.get("oneway", "")).lower()
        assumed_oneway = road_class in {"motorway", "motorway_link"} or tags.get("junction") == "roundabout"
        is_oneway = oneway_value in {"yes", "1", "true", "-1"} or (assumed_oneway and oneway_value != "no")
        if oneway_value == "-1":
            node_ids.reverse()
        way_id = str(way["id"])
        for index, (start, end) in enumerate(zip(node_ids[:-1], node_ids[1:], strict=True)):
            used_nodes.update((start, end))
            geometry = (raw_nodes[start], raw_nodes[end])
            common = {
                "osm_way_id": way_id,
                "geometry": geometry,
                "road_class": road_class,
                "road_name": tags.get("name") or tags.get("ref"),
                "maxspeed": tags.get("maxspeed"),
                "oneway": is_oneway,
            }
            edges.append(RoadEdge(f"w{way_id}:{index}:f", from_node=start, to_node=end, **common))
            if not is_oneway:
                edges.append(
                    RoadEdge(
                        f"w{way_id}:{index}:r",
                        from_node=end,
                        to_node=start,
                        **{**common, "geometry": tuple(reversed(geometry))},
                    )
                )
    nodes = {
        node_id: RoadNode(node_id, raw_nodes[node_id][0], raw_nodes[node_id][1])
        for node_id in sorted(used_nodes, key=int)
    }
    metadata = {
        "source": config["source"],
        "license": config["license"],
        "attribution": "© OpenStreetMap contributors",
        "bounds_wgs84": config["bounds_wgs84"],
        "road_classes_retained": config["road_classes"],
        "static_region_policy": config["static_region_policy"],
        "source_timestamp": payload.get("osm3s", {}).get("timestamp_osm_base"),
        "built_utc": datetime.now(timezone.utc).isoformat(),
        "coordinate_storage": "WGS84-like OSM latitude/longitude; converted at runtime to the project's local spherical tangent approximation",
    }
    return RoadGraph(nodes, edges, metadata)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/phase6/io_vnbd_s1_map.json")
    parser.add_argument("--payload", help="Optional existing Overpass JSON response")
    args = parser.parse_args()
    config_path = _resolve(args.config)
    config = _load_json(config_path)
    payload = _load_json(_resolve(args.payload)) if args.payload else _download(config)
    graph = build_graph(payload, config)
    cache_path = _resolve(config["cache_path"])
    graph.save(cache_path)
    classes = Counter(edge.road_class for edge in graph.edges)
    metadata = {
        **graph.metadata,
        "schema_version": 1,
        "cache_path": str(cache_path.relative_to(ROOT)).replace("\\", "/"),
        "cache_sha256": _sha256(cache_path),
        "cache_size_bytes": cache_path.stat().st_size,
        "node_count": len(graph.nodes),
        "directed_edge_count": len(graph.edges),
        "directed_edge_count_by_class": dict(sorted(classes.items())),
        "overpass_query": _overpass_query(config),
        "runtime_network_required": False,
    }
    metadata_path = _resolve(config["metadata_path"])
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(metadata, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
