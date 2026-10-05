"""Phase 6 geometry, topology, hypothesis, leakage, and S1 smoke tests."""

from __future__ import annotations

import inspect
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from idr.evaluation import geodetic_to_local_xy_m, local_xy_to_geodetic
from idr.io_vnbd import load_journey
from idr.map_matching import (
    MapMatcherConfig,
    ProbabilisticMapMatcher,
    RoadEdge,
    RoadGraph,
    RoadNode,
    angle_difference_deg,
    local_tangent_bearing_deg,
    nearest_road_match,
    project_onto_polyline,
)
from idr.map_matching.matcher import (
    _normalized_probabilities,
    generate_candidates,
    matcher_api_is_reference_free,
    network_transition_distance_m,
    transition_log_score,
)
from idr.map_matching.road_graph import LocalRoadEdge, LocalRoadGraph


def _edge(
    edge_id: str,
    start: str,
    end: str,
    points: list[tuple[float, float]],
    *,
    road_class: str = "residential",
    oneway: bool = False,
) -> LocalRoadEdge:
    array = np.asarray(points, dtype=float)
    cumulative = np.concatenate(([0.0], np.cumsum(np.linalg.norm(np.diff(array, axis=0), axis=1))))
    return LocalRoadEdge(
        edge_id=edge_id,
        osm_way_id=edge_id,
        from_node=start,
        to_node=end,
        points_xy_m=array,
        cumulative_lengths_m=cumulative,
        length_m=float(cumulative[-1]),
        road_class=road_class,
        road_name=edge_id,
        maxspeed=None,
        oneway=oneway,
    )


def _graph(*, include_parallel: bool = False, include_branches: bool = False) -> LocalRoadGraph:
    nodes = {
        "a0": (0.0, 0.0),
        "a1": (0.0, 100.0),
        "a2": (0.0, 200.0),
        "b0": (10.0, 0.0),
        "b2": (10.0, 200.0),
        "left": (-100.0, 200.0),
        "right": (100.0, 200.0),
    }
    edges = [
        _edge("straight_1", "a0", "a1", [(0, 0), (0, 100)]),
        _edge("straight_2", "a1", "a2", [(0, 100), (0, 200)]),
    ]
    if include_parallel:
        edges.append(_edge("parallel", "b0", "b2", [(10, 0), (10, 200)]))
    if include_branches:
        edges.extend(
            [
                _edge("left_branch", "a1", "left", [(0, 100), (-100, 200)]),
                _edge("right_branch", "a1", "right", [(0, 100), (100, 200)]),
            ]
        )
    return LocalRoadGraph(nodes, edges, 52.0, -1.5, grid_cell_size_m=25.0)


def _prior(
    xy: list[tuple[float, float]],
    yaw: list[float] | None = None,
    sigma: float = 5.0,
    speed: float = 10.0,
) -> pd.DataFrame:
    count = len(xy)
    return pd.DataFrame(
        {
            "elapsed_s": np.arange(count, dtype=float),
            "estimated_x_m": [point[0] for point in xy],
            "estimated_y_m": [point[1] for point in xy],
            "estimated_speed_mps": np.full(count, speed),
            "estimated_yaw_deg": yaw if yaw is not None else np.zeros(count),
            "horizontal_position_sigma_m": np.full(count, sigma),
        }
    )


# A. Coordinate tests
def test_01_origin_round_trip() -> None:
    frame = geodetic_to_local_xy_m([52.4], [-1.55], 52.4, -1.55)
    lat, lon = local_xy_to_geodetic(frame.x_east_m, frame.y_north_m, 52.4, -1.55)
    assert lat[0] == pytest.approx(52.4)
    assert lon[0] == pytest.approx(-1.55)


def test_02_latlon_xy_latlon_round_trip() -> None:
    latitude = np.array([52.4, 52.401, 52.399])
    longitude = np.array([-1.55, -1.548, -1.552])
    frame = geodetic_to_local_xy_m(latitude, longitude, 52.4, -1.55)
    lat, lon = local_xy_to_geodetic(frame.x_east_m, frame.y_north_m, 52.4, -1.55)
    assert np.allclose(lat, latitude)
    assert np.allclose(lon, longitude)


def test_03_east_north_sign_correctness() -> None:
    frame = geodetic_to_local_xy_m([52.401], [-1.549], 52.4, -1.55)
    assert frame.x_east_m[0] > 0 and frame.y_north_m[0] > 0


def test_04_local_coordinates_are_finite() -> None:
    frame = geodetic_to_local_xy_m([52.4, 52.41], [-1.55, -1.50], 52.4, -1.55)
    assert np.all(np.isfinite(frame.x_east_m)) and np.all(np.isfinite(frame.y_north_m))


# B. Road geometry tests
def test_05_projection_onto_straight_road() -> None:
    projection = project_onto_polyline((3, 4), [(0, 0), (0, 10)])
    assert (projection.x_m, projection.y_m) == pytest.approx((0, 4))


def test_06_projection_onto_curved_polyline_uses_nearest_segment() -> None:
    projection = project_onto_polyline((8, 12), [(0, 0), (0, 10), (10, 10)])
    assert projection.segment_index == 1
    assert (projection.x_m, projection.y_m) == pytest.approx((8, 10))


def test_07_local_tangent_bearing() -> None:
    assert local_tangent_bearing_deg((0, 0), (0, 10)) == pytest.approx(0)
    assert local_tangent_bearing_deg((0, 0), (10, 0)) == pytest.approx(90)


def test_08_distance_to_road() -> None:
    assert project_onto_polyline((3, 4), [(0, 0), (0, 10)]).distance_m == pytest.approx(3)


# C. Candidate tests
def test_09_nearby_candidate_is_found() -> None:
    candidates, _ = generate_candidates(_graph(), 2, 50, 0, 5, 3, MapMatcherConfig())
    assert candidates and candidates[0].edge_id == "straight_1"


def test_10_distant_road_is_excluded() -> None:
    config = MapMatcherConfig(maximum_search_radius_m=20)
    candidates, _ = generate_candidates(_graph(), 100, 50, 0, 5, 1, config)
    assert not candidates


def test_11_uncertainty_expands_search_radius() -> None:
    config = MapMatcherConfig()
    assert config.search_radius_m(50) > config.search_radius_m(1)


def test_12_top_k_is_respected() -> None:
    config = MapMatcherConfig(top_k_candidates=2)
    candidates, _ = generate_candidates(_graph(include_parallel=True, include_branches=True), 5, 100, 0, 5, 20, config)
    assert len(candidates) <= 2


def test_13_non_vehicle_road_is_filtered() -> None:
    nodes = {"a": RoadNode("a", 52.4, -1.55), "b": RoadNode("b", 52.401, -1.55), "c": RoadNode("c", 52.4, -1.549)}
    graph = RoadGraph(nodes, [
        RoadEdge("foot", "1", "a", "b", ((52.4, -1.55), (52.401, -1.55)), "footway"),
        RoadEdge("road", "2", "a", "c", ((52.4, -1.55), (52.4, -1.549)), "residential"),
    ])
    assert [edge.edge_id for edge in graph.edges] == ["road"]


# D. Heading tests
def test_14_heading_wrap_359_vs_1() -> None:
    assert angle_difference_deg(359, 1) == pytest.approx(-2)


def test_15_bidirectional_road_handles_both_directions() -> None:
    graph = LocalRoadGraph(
        {"a": (0, 0), "b": (0, 100)},
        [_edge("north", "a", "b", [(0, 0), (0, 100)]), _edge("south", "b", "a", [(0, 100), (0, 0)])],
        52, -1.5,
    )
    north, _ = generate_candidates(graph, 0, 50, 0, 5, 3, MapMatcherConfig())
    south, _ = generate_candidates(graph, 0, 50, 180, 5, 3, MapMatcherConfig())
    assert north[0].edge_id == "north" and south[0].edge_id == "south"


def test_16_one_way_opposite_direction_is_penalized() -> None:
    graph = LocalRoadGraph({"a": (0, 0), "b": (0, 100)}, [_edge("oneway", "a", "b", [(0, 0), (0, 100)], oneway=True)], 52, -1.5)
    with_flow, _ = generate_candidates(graph, 0, 50, 0, 5, 3, MapMatcherConfig())
    opposing, _ = generate_candidates(graph, 0, 50, 180, 5, 3, MapMatcherConfig())
    assert opposing[0].heading_log_score < with_flow[0].heading_log_score - 9


# E. Transition tests
def test_17_connected_edge_transition_is_preferred() -> None:
    graph = _graph(include_parallel=True)
    config = MapMatcherConfig()
    previous = generate_candidates(graph, 0, 95, 0, 10, 3, config)[0][0]
    current = generate_candidates(graph, 0, 105, 0, 10, 3, config)[0][0]
    parallel = next(item for item in generate_candidates(graph, 10, 105, 0, 10, 3, config)[0] if item.edge_id == "parallel")
    connected_score = transition_log_score(graph, previous, current, 10, 0, 10, config)[0]
    parallel_score = transition_log_score(graph, previous, parallel, 10, 0, 10, config)[0]
    assert connected_score > parallel_score


def test_18_impossible_graph_jump_is_rejected() -> None:
    graph = _graph(include_parallel=True)
    config = MapMatcherConfig()
    previous = next(item for item in generate_candidates(graph, 0, 50, 0, 10, 3, config)[0] if item.edge_id == "straight_1")
    current = next(item for item in generate_candidates(graph, 10, 60, 0, 10, 3, config)[0] if item.edge_id == "parallel")
    _, impossible, distance = transition_log_score(graph, previous, current, 10, 0, 10, config)
    assert impossible and math.isinf(distance)


def test_19_network_distance_matches_connected_progress() -> None:
    graph = _graph()
    config = MapMatcherConfig()
    previous = generate_candidates(graph, 0, 95, 0, 10, 3, config)[0][0]
    current = generate_candidates(graph, 0, 105, 0, 10, 3, config)[0][0]
    assert network_transition_distance_m(graph, previous, current, 50) == pytest.approx(10)


def test_20_turn_consistency_changes_score() -> None:
    graph = _graph(include_branches=True)
    config = MapMatcherConfig()
    previous = next(item for item in generate_candidates(graph, 0, 95, 0, 10, 3, config)[0] if item.edge_id == "straight_1")
    left = next(item for item in generate_candidates(graph, -5, 105, 315, 10, 10, config)[0] if item.edge_id == "left_branch")
    correct = transition_log_score(graph, previous, left, 10, -45, 10, config)[0]
    wrong = transition_log_score(graph, previous, left, 10, 45, 10, config)[0]
    assert correct > wrong


def test_21_stationary_transition_prefers_no_motion() -> None:
    graph = _graph()
    config = MapMatcherConfig()
    previous = generate_candidates(graph, 0, 50, 0, 0, 3, config)[0][0]
    same = generate_candidates(graph, 0, 50, 0, 0, 3, config)[0][0]
    moved = generate_candidates(graph, 0, 60, 0, 0, 3, config)[0][0]
    assert transition_log_score(graph, previous, same, 0, 0, 0, config)[0] > transition_log_score(graph, previous, moved, 0, 0, 0, config)[0]


# F. Hypothesis tests
def test_22_multiple_hypotheses_are_retained() -> None:
    result = ProbabilisticMapMatcher(_graph(include_parallel=True), MapMatcherConfig()).match(_prior([(5, 50)]), "test")
    assert result.data["retained_hypothesis_count"].iloc[0] >= 2


def test_23_beam_pruning_works() -> None:
    config = MapMatcherConfig(top_k_candidates=8, beam_width=2)
    result = ProbabilisticMapMatcher(_graph(include_parallel=True, include_branches=True), config).match(_prior([(2, 100)]), "test")
    assert result.data["retained_hypothesis_count"].iloc[0] <= 2


def test_24_log_probabilities_remain_finite() -> None:
    result = ProbabilisticMapMatcher(_graph(include_parallel=True), MapMatcherConfig()).match(_prior([(5, y) for y in range(10, 100, 10)]), "test")
    assert np.all(np.isfinite(result.data["top_probability"]))


def test_25_probability_normalization_is_valid() -> None:
    probabilities = _normalized_probabilities(np.array([-10000.0, -10001.0, -10002.0]))
    assert probabilities.sum() == pytest.approx(1.0) and np.all(probabilities >= 0)


def test_26_ambiguity_is_detected_between_parallel_roads() -> None:
    config = MapMatcherConfig(ambiguity_probability_gap=0.2, ambiguity_entropy_fraction=0.5)
    result = ProbabilisticMapMatcher(_graph(include_parallel=True), config).match(_prior([(5, 50)]), "test")
    assert result.data["map_match_status"].iloc[0] == "AMBIGUOUS"


# G. Fallback tests
def test_27_no_candidate_returns_unconstrained_estimator() -> None:
    prior = _prior([(500, 500)])
    result = ProbabilisticMapMatcher(_graph(), MapMatcherConfig(maximum_search_radius_m=20)).match(prior, "test")
    assert result.data["map_match_status"].iloc[0] == "NO_CANDIDATE"
    assert result.data[["matched_east_m", "matched_north_m"]].iloc[0].tolist() == pytest.approx([500, 500])


def test_28_bad_map_geometry_does_not_crash_estimator() -> None:
    bad = _edge("bad", "a", "b", [(0, 0), (0, 1)])
    object.__setattr__(bad, "points_xy_m", np.array([[np.nan, 0], [np.nan, 1]]))
    graph = LocalRoadGraph({"a": (0, 0), "b": (0, 1)}, [bad], 52, -1.5)
    result = ProbabilisticMapMatcher(graph, MapMatcherConfig()).match(_prior([(0, 0)]), "test")
    assert result.data["map_match_status"].iloc[0] == "NO_CANDIDATE"


def test_29_low_confidence_correction_is_not_forced() -> None:
    config = MapMatcherConfig(minimum_apply_probability=0.99)
    prior = _prior([(5, 50)])
    result = ProbabilisticMapMatcher(_graph(include_parallel=True), config).match(prior, "test")
    assert result.data["map_match_status"].iloc[0] == "DEGRADED"
    assert result.data["matched_east_m"].iloc[0] == pytest.approx(5)


# H. Leakage tests
def test_30_matcher_api_accepts_no_evaluation_reference() -> None:
    assert matcher_api_is_reference_free()


def test_31_matcher_requires_no_vbox() -> None:
    result = ProbabilisticMapMatcher(_graph(), MapMatcherConfig()).match(_prior([(0, 50)]), "test")
    assert len(result.data) == 1


def test_32_future_phone_gnss_is_rejected() -> None:
    prior = _prior([(0, 50)])
    prior["gps_latitude_deg"] = 52.4
    with pytest.raises(ValueError, match="forbidden"):
        ProbabilisticMapMatcher(_graph(), MapMatcherConfig()).match(prior, "test")


def test_33_route_polyline_is_absent_from_matcher_api() -> None:
    assert "route" not in inspect.signature(ProbabilisticMapMatcher.match).parameters


def test_34_scenario_truth_is_absent_from_matcher_api() -> None:
    parameters = inspect.signature(ProbabilisticMapMatcher.match).parameters
    assert "truth" not in parameters and "scenario" not in parameters


# I. Integration tests
def test_35_synthetic_straight_road_tracks_connected_edge() -> None:
    result = ProbabilisticMapMatcher(_graph(), MapMatcherConfig()).match(_prior([(2, 20), (3, 30), (4, 40)]), "test")
    assert np.allclose(result.data["matched_east_m"], 0)


def test_36_synthetic_parallel_road_preserves_topology_history() -> None:
    result = ProbabilisticMapMatcher(_graph(include_parallel=True), MapMatcherConfig()).match(_prior([(1, 20), (4.9, 30), (5.1, 40)]), "test")
    assert result.data["road_edge_id"].iloc[-1] == "straight_1"


def test_37_synthetic_junction_retains_multiple_branches() -> None:
    result = ProbabilisticMapMatcher(_graph(include_branches=True), MapMatcherConfig()).match(_prior([(0, 95)]), "test")
    assert result.data["retained_hypothesis_count"].iloc[0] >= 3


def test_38_synthetic_left_turn_shifts_to_left_branch() -> None:
    prior = _prior([(0, 90), (-7, 107), (-20, 120)], yaw=[0, 330, 315])
    result = ProbabilisticMapMatcher(_graph(include_branches=True), MapMatcherConfig()).match(prior, "test")
    assert result.data["road_edge_id"].iloc[-1] == "left_branch"


def test_39_synthetic_one_way_uses_legal_direction() -> None:
    graph = LocalRoadGraph({"a": (0, 0), "b": (0, 100)}, [_edge("north_only", "a", "b", [(0, 0), (0, 100)], oneway=True)], 52, -1.5)
    result = ProbabilisticMapMatcher(graph, MapMatcherConfig()).match(_prior([(0, 20), (0, 30)], yaw=[0, 0]), "test")
    assert set(result.data["road_edge_id"]) == {"north_only"}


def test_40_s1_static_map_smoke() -> None:
    journey = load_journey("S1", project_root_path=ROOT)
    graph = RoadGraph.load(ROOT / "data/map_cache/io_vnbd_s1/road_graph.json.gz")
    first = journey.smartphone.iloc[0]
    local = graph.localize(float(first["gps_latitude_deg"]), float(first["gps_longitude_deg"]), 75)
    candidates, radius = generate_candidates(local, 0, 0, float(first["gps_orientation_deg"]), float(first["gps_speed_mps"]), 5, MapMatcherConfig())
    assert candidates and radius >= 15
