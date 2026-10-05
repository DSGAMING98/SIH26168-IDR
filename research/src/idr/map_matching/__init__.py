"""Offline, leakage-resistant probabilistic map matching for Phase 6."""

from .matcher import (
    MapHypothesis,
    MapMatchResult,
    MapMatcherConfig,
    ProbabilisticMapMatcher,
    RoadCandidate,
    angle_difference_deg,
    nearest_road_match,
)
from .evaluation import MapMatchEvaluation, as_raw_map_prediction, evaluate_map_match
from .road_graph import (
    LocalRoadGraph,
    RoadEdge,
    RoadGraph,
    RoadNode,
    local_tangent_bearing_deg,
    project_onto_polyline,
)

__all__ = [
    "LocalRoadGraph",
    "MapHypothesis",
    "MapMatchEvaluation",
    "MapMatchResult",
    "MapMatcherConfig",
    "ProbabilisticMapMatcher",
    "RoadCandidate",
    "RoadEdge",
    "RoadGraph",
    "RoadNode",
    "angle_difference_deg",
    "as_raw_map_prediction",
    "evaluate_map_match",
    "local_tangent_bearing_deg",
    "nearest_road_match",
    "project_onto_polyline",
]
