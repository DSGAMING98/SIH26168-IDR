"""Compact geographic road graph and local-metric spatial index.

The cache stores latitude/longitude as supplied by OpenStreetMap.  A graph is
projected into the same spherical local tangent approximation used by the
existing evaluation utilities for each experiment's pre-blackout phone-GNSS
origin.  It is not represented as a surveyed or EPSG-qualified CRS.
"""

from __future__ import annotations

import gzip
import heapq
import io
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from ..evaluation import geodetic_to_local_xy_m


VEHICLE_ROAD_CLASSES: frozenset[str] = frozenset(
    {
        "motorway",
        "motorway_link",
        "trunk",
        "trunk_link",
        "primary",
        "primary_link",
        "secondary",
        "secondary_link",
        "tertiary",
        "tertiary_link",
        "residential",
        "unclassified",
        "service",
        "living_street",
    }
)


@dataclass(frozen=True)
class RoadNode:
    node_id: str
    latitude_deg: float
    longitude_deg: float


@dataclass(frozen=True)
class RoadEdge:
    edge_id: str
    osm_way_id: str
    from_node: str
    to_node: str
    geometry: tuple[tuple[float, float], ...]
    road_class: str
    road_name: str | None = None
    maxspeed: str | None = None
    oneway: bool = False


@dataclass(frozen=True)
class LocalRoadEdge:
    edge_id: str
    osm_way_id: str
    from_node: str
    to_node: str
    points_xy_m: np.ndarray
    cumulative_lengths_m: np.ndarray
    length_m: float
    road_class: str
    road_name: str | None
    maxspeed: str | None
    oneway: bool


@dataclass(frozen=True)
class PolylineProjection:
    x_m: float
    y_m: float
    distance_m: float
    along_m: float
    fraction: float
    segment_index: int
    bearing_deg: float


def local_tangent_bearing_deg(start_xy: Iterable[float], end_xy: Iterable[float]) -> float:
    """Bearing clockwise from local North for one non-degenerate segment."""

    start = np.asarray(tuple(start_xy), dtype=float)
    end = np.asarray(tuple(end_xy), dtype=float)
    if start.shape != (2,) or end.shape != (2,) or not np.all(np.isfinite([start, end])):
        raise ValueError("Bearing endpoints must be finite two-dimensional points.")
    delta = end - start
    if float(np.linalg.norm(delta)) <= 0.0:
        raise ValueError("Cannot compute bearing for a zero-length segment.")
    return float(np.degrees(np.arctan2(delta[0], delta[1])) % 360.0)


def project_onto_polyline(point_xy: Iterable[float], points_xy: Any) -> PolylineProjection:
    """Return the nearest point and local tangent on a metric polyline."""

    point = np.asarray(tuple(point_xy), dtype=float)
    points = np.asarray(points_xy, dtype=float)
    if point.shape != (2,) or not np.all(np.isfinite(point)):
        raise ValueError("Projection point must be finite and two-dimensional.")
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 2:
        raise ValueError("Road geometry must contain at least two XY points.")
    if not np.all(np.isfinite(points)):
        raise ValueError("Road geometry contains non-finite coordinates.")
    vectors = np.diff(points, axis=0)
    lengths_squared = np.sum(vectors * vectors, axis=1)
    valid = lengths_squared > 1e-12
    if not bool(np.any(valid)):
        raise ValueError("Road geometry is entirely degenerate.")
    fractions = np.zeros(len(vectors), dtype=float)
    fractions[valid] = np.clip(
        np.sum((point - points[:-1][valid]) * vectors[valid], axis=1)
        / lengths_squared[valid],
        0.0,
        1.0,
    )
    projected = points[:-1] + fractions[:, None] * vectors
    distances = np.linalg.norm(projected - point, axis=1)
    distances[~valid] = np.inf
    segment = int(np.argmin(distances))
    segment_lengths = np.sqrt(lengths_squared)
    cumulative = np.concatenate(([0.0], np.cumsum(segment_lengths)))
    along = float(cumulative[segment] + fractions[segment] * segment_lengths[segment])
    total = float(cumulative[-1])
    return PolylineProjection(
        x_m=float(projected[segment, 0]),
        y_m=float(projected[segment, 1]),
        distance_m=float(distances[segment]),
        along_m=along,
        fraction=float(along / total),
        segment_index=segment,
        bearing_deg=local_tangent_bearing_deg(points[segment], points[segment + 1]),
    )


class RoadGraph:
    """Geographic directed road graph read from the deterministic local cache."""

    def __init__(self, nodes: dict[str, RoadNode], edges: Iterable[RoadEdge], metadata: dict[str, Any] | None = None):
        self.nodes = dict(nodes)
        self.edges = tuple(edge for edge in edges if edge.road_class in VEHICLE_ROAD_CLASSES)
        self.metadata = dict(metadata or {})
        if not self.nodes or not self.edges:
            raise ValueError("Road graph requires nodes and vehicle-road edges.")

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "RoadGraph":
        nodes = {item["node_id"]: RoadNode(**item) for item in values["nodes"]}
        edges = []
        for item in values["edges"]:
            record = dict(item)
            record["geometry"] = tuple(tuple(point) for point in record["geometry"])
            edges.append(RoadEdge(**record))
        return cls(nodes, edges, values.get("metadata", {}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "metadata": self.metadata,
            "nodes": [asdict(node) for node in self.nodes.values()],
            "edges": [asdict(edge) for edge in self.edges],
        }

    @classmethod
    def load(cls, path: Path | str) -> "RoadGraph":
        source = Path(path)
        if source.suffix == ".gz":
            with gzip.open(source, "rt", encoding="utf-8") as stream:
                return cls.from_dict(json.load(stream))
        with source.open(encoding="utf-8") as stream:
            return cls.from_dict(json.load(stream))

    def save(self, path: Path | str) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.suffix == ".gz":
            with destination.open("wb") as raw:
                with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
                    with io.TextIOWrapper(zipped, encoding="utf-8") as stream:
                        json.dump(self.to_dict(), stream, separators=(",", ":"), sort_keys=True)
            return
        with destination.open("w", encoding="utf-8") as stream:
            json.dump(self.to_dict(), stream, indent=2, sort_keys=True)
            stream.write("\n")

    def localize(
        self,
        origin_latitude_deg: float,
        origin_longitude_deg: float,
        grid_cell_size_m: float = 75.0,
    ) -> "LocalRoadGraph":
        local_edges: list[LocalRoadEdge] = []
        node_xy: dict[str, tuple[float, float]] = {}
        for node_id, node in self.nodes.items():
            local = geodetic_to_local_xy_m(
                [node.latitude_deg], [node.longitude_deg], origin_latitude_deg, origin_longitude_deg
            )
            node_xy[node_id] = (float(local.x_east_m[0]), float(local.y_north_m[0]))
        for edge in self.edges:
            latitude = [point[0] for point in edge.geometry]
            longitude = [point[1] for point in edge.geometry]
            local = geodetic_to_local_xy_m(
                latitude, longitude, origin_latitude_deg, origin_longitude_deg
            )
            points = np.column_stack((local.x_east_m, local.y_north_m))
            lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
            if len(points) < 2 or not np.all(np.isfinite(points)) or float(np.sum(lengths)) <= 1e-6:
                continue
            cumulative = np.concatenate(([0.0], np.cumsum(lengths)))
            local_edges.append(
                LocalRoadEdge(
                    edge_id=edge.edge_id,
                    osm_way_id=edge.osm_way_id,
                    from_node=edge.from_node,
                    to_node=edge.to_node,
                    points_xy_m=points,
                    cumulative_lengths_m=cumulative,
                    length_m=float(cumulative[-1]),
                    road_class=edge.road_class,
                    road_name=edge.road_name,
                    maxspeed=edge.maxspeed,
                    oneway=edge.oneway,
                )
            )
        return LocalRoadGraph(
            node_xy=node_xy,
            edges=local_edges,
            origin_latitude_deg=origin_latitude_deg,
            origin_longitude_deg=origin_longitude_deg,
            grid_cell_size_m=grid_cell_size_m,
        )


class LocalRoadGraph:
    """Local metric graph with a uniform-grid edge index and directed adjacency."""

    def __init__(
        self,
        node_xy: dict[str, tuple[float, float]],
        edges: Iterable[LocalRoadEdge],
        origin_latitude_deg: float,
        origin_longitude_deg: float,
        grid_cell_size_m: float = 75.0,
    ):
        if not np.isfinite(grid_cell_size_m) or grid_cell_size_m <= 0:
            raise ValueError("Spatial-index grid cell size must be positive.")
        self.node_xy = dict(node_xy)
        self.edges: dict[str, LocalRoadEdge] = {}
        self.origin_latitude_deg = float(origin_latitude_deg)
        self.origin_longitude_deg = float(origin_longitude_deg)
        self.grid_cell_size_m = float(grid_cell_size_m)
        self.adjacency: dict[str, list[tuple[str, float, str]]] = {}
        self._grid: dict[tuple[int, int], list[str]] = {}
        self._shortest_distance_cache: dict[tuple[str, str], float] = {}
        for edge in edges:
            points = np.asarray(edge.points_xy_m, dtype=float)
            if (
                points.ndim != 2
                or points.shape[1] != 2
                or len(points) < 2
                or not np.all(np.isfinite(points))
                or not np.isfinite(edge.length_m)
                or edge.length_m <= 1e-6
            ):
                continue
            self.edges[edge.edge_id] = edge
            self.adjacency.setdefault(edge.from_node, []).append(
                (edge.to_node, edge.length_m, edge.edge_id)
            )
            minimum = np.min(edge.points_xy_m, axis=0)
            maximum = np.max(edge.points_xy_m, axis=0)
            x0, y0 = self._cell(minimum[0], minimum[1])
            x1, y1 = self._cell(maximum[0], maximum[1])
            for cell_x in range(x0, x1 + 1):
                for cell_y in range(y0, y1 + 1):
                    self._grid.setdefault((cell_x, cell_y), []).append(edge.edge_id)

    def _cell(self, x_m: float, y_m: float) -> tuple[int, int]:
        return (
            math.floor(float(x_m) / self.grid_cell_size_m),
            math.floor(float(y_m) / self.grid_cell_size_m),
        )

    def nearby_edge_ids(self, x_m: float, y_m: float, radius_m: float) -> tuple[str, ...]:
        if not np.all(np.isfinite([x_m, y_m, radius_m])) or radius_m <= 0:
            raise ValueError("Candidate query requires finite coordinates and positive radius.")
        x0, y0 = self._cell(x_m - radius_m, y_m - radius_m)
        x1, y1 = self._cell(x_m + radius_m, y_m + radius_m)
        found: set[str] = set()
        for cell_x in range(x0, x1 + 1):
            for cell_y in range(y0, y1 + 1):
                found.update(self._grid.get((cell_x, cell_y), ()))
        return tuple(sorted(found))

    def shortest_node_distance_m(
        self, start_node: str, end_node: str, maximum_distance_m: float
    ) -> float:
        """Limited directed Dijkstra used only between map-match candidates."""

        if start_node == end_node:
            return 0.0
        cached = self._shortest_distance_cache.get((start_node, end_node))
        if cached is not None:
            return cached if cached <= maximum_distance_m else math.inf
        queue: list[tuple[float, str]] = [(0.0, start_node)]
        best = {start_node: 0.0}
        while queue:
            distance, node = heapq.heappop(queue)
            if distance != best.get(node) or distance > maximum_distance_m:
                continue
            if node == end_node:
                self._shortest_distance_cache[(start_node, end_node)] = distance
                return distance
            for target, edge_length, _ in self.adjacency.get(node, ()):
                new_distance = distance + edge_length
                if new_distance <= maximum_distance_m and new_distance < best.get(target, math.inf):
                    best[target] = new_distance
                    heapq.heappush(queue, (new_distance, target))
        return math.inf
