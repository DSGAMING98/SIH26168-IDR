"""Uncertainty-aware candidate scoring and beam/HMM-style map matching."""

from __future__ import annotations

import inspect
import math
import time
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from ..blackout import EvaluationReference, GNSS_DERIVED_FIELDS
from ..evaluation import local_xy_to_geodetic
from .road_graph import LocalRoadEdge, LocalRoadGraph, project_onto_polyline


RUNTIME_PRIOR_FIELDS = frozenset(
    {
        "elapsed_s",
        "estimated_x_m",
        "estimated_y_m",
        "estimated_speed_mps",
        "estimated_yaw_deg",
        "horizontal_position_sigma_m",
    }
)


def angle_difference_deg(first_deg: float, second_deg: float) -> float:
    """Smallest signed circular difference ``first - second`` in degrees."""

    return float((float(first_deg) - float(second_deg) + 180.0) % 360.0 - 180.0)


@dataclass(frozen=True)
class MapMatcherConfig:
    base_search_radius_m: float = 15.0
    uncertainty_radius_scale: float = 1.5
    minimum_search_radius_m: float = 15.0
    maximum_search_radius_m: float = 180.0
    top_k_candidates: int = 8
    beam_width: int = 8
    distance_sigma_floor_m: float = 5.0
    distance_uncertainty_scale: float = 0.35
    distance_sigma_cap_m: float = 60.0
    heading_sigma_deg: float = 32.0
    transition_distance_sigma_m: float = 8.0
    turn_sigma_deg: float = 35.0
    edge_switch_log_penalty: float = 0.25
    impossible_transition_log_penalty: float = 22.0
    one_way_opposition_log_penalty: float = 10.0
    ambiguity_probability_gap: float = 0.12
    ambiguity_entropy_fraction: float = 0.72
    minimum_apply_probability: float = 0.12
    maximum_correction_m: float = 120.0
    maximum_network_search_m: float = 250.0
    stationary_speed_threshold_mps: float = 0.4
    stationary_motion_tolerance_m: float = 2.0
    grid_cell_size_m: float = 75.0

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "MapMatcherConfig":
        allowed = {field.name for field in cls.__dataclass_fields__.values()}
        unknown = set(values).difference(allowed)
        if unknown:
            raise ValueError(f"Unknown map-matcher settings: {sorted(unknown)}")
        result = cls(**values)
        result.validate()
        return result

    def validate(self) -> None:
        numeric = [
            value
            for key, value in asdict(self).items()
            if key not in {"top_k_candidates", "beam_width"}
        ]
        if not np.all(np.isfinite(numeric)) or any(value < 0 for value in numeric):
            raise ValueError("Map-matcher numeric settings must be finite and non-negative.")
        if self.minimum_search_radius_m <= 0 or self.maximum_search_radius_m < self.minimum_search_radius_m:
            raise ValueError("Invalid candidate search-radius limits.")
        if self.top_k_candidates <= 0 or self.beam_width <= 0:
            raise ValueError("Candidate top K and beam width must be positive.")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def search_radius_m(self, position_sigma_m: float) -> float:
        sigma = max(0.0, float(position_sigma_m))
        return float(
            np.clip(
                self.base_search_radius_m + self.uncertainty_radius_scale * sigma,
                self.minimum_search_radius_m,
                self.maximum_search_radius_m,
            )
        )


@dataclass(frozen=True)
class RoadCandidate:
    edge_id: str
    projected_x_m: float
    projected_y_m: float
    along_m: float
    fraction: float
    distance_m: float
    road_bearing_deg: float
    road_class: str
    road_name: str | None
    oneway: bool
    distance_log_score: float
    heading_log_score: float
    speed_class_log_score: float
    emission_log_score: float


@dataclass(frozen=True)
class MapHypothesis:
    candidate: RoadCandidate
    log_probability: float
    predecessor_edge_id: str | None
    impossible_transition_rejections: int = 0


@dataclass(frozen=True)
class MapMatchResult:
    data: pd.DataFrame
    candidate_generation_seconds: float
    matching_seconds: float
    input_estimator: str
    algorithm: str = "phase6_probabilistic_beam_map_matcher_v1"


def _speed_class_score(speed_mps: float, road_class: str) -> float:
    if speed_mps > 18.0 and road_class in {"service", "living_street"}:
        return -1.5
    if speed_mps > 28.0 and road_class == "residential":
        return -1.0
    return 0.0


def _validate_runtime_prior(prior: pd.DataFrame) -> pd.DataFrame:
    if isinstance(prior, EvaluationReference):
        raise TypeError("Map matcher accepts a Phase 5 runtime prior, never EvaluationReference.")
    leaked = set(GNSS_DERIVED_FIELDS).intersection(prior.columns)
    leaked.update(column for column in prior.columns if "vbox" in column.lower() or "reference" in column.lower())
    if leaked:
        raise ValueError(f"Map-matcher runtime prior exposes forbidden fields: {sorted(leaked)}")
    missing = RUNTIME_PRIOR_FIELDS.difference(prior.columns)
    if missing:
        raise ValueError(f"Map-matcher runtime prior is missing fields: {sorted(missing)}")
    # Copy only the declared runtime interface.  Extra estimator diagnostics
    # cannot accidentally become future score inputs without an explicit API
    # and test change.
    frame = prior.loc[:, sorted(RUNTIME_PRIOR_FIELDS)].reset_index(drop=True).copy()
    values = frame.loc[:, sorted(RUNTIME_PRIOR_FIELDS)].to_numpy(dtype=float)
    if frame.empty or not np.all(np.isfinite(values)):
        raise ValueError("Map-matcher runtime prior must be non-empty and finite.")
    elapsed = frame["elapsed_s"].to_numpy(dtype=float)
    if len(elapsed) > 1 and np.any(np.diff(elapsed) <= 0):
        raise ValueError("Map-matcher timestamps must be strictly increasing.")
    return frame


def generate_candidates(
    graph: LocalRoadGraph,
    x_m: float,
    y_m: float,
    yaw_deg: float,
    speed_mps: float,
    position_sigma_m: float,
    config: MapMatcherConfig,
) -> tuple[list[RoadCandidate], float]:
    radius = config.search_radius_m(position_sigma_m)
    sigma_distance = float(
        np.clip(
            config.distance_uncertainty_scale * position_sigma_m,
            config.distance_sigma_floor_m,
            config.distance_sigma_cap_m,
        )
    )
    candidates: list[RoadCandidate] = []
    for edge_id in graph.nearby_edge_ids(x_m, y_m, radius):
        edge = graph.edges.get(edge_id)
        if edge is None:
            continue
        try:
            projection = project_onto_polyline((x_m, y_m), edge.points_xy_m)
        except ValueError:
            continue
        if projection.distance_m > radius:
            continue
        heading_delta = angle_difference_deg(yaw_deg, projection.bearing_deg)
        distance_score = -0.5 * (projection.distance_m / sigma_distance) ** 2
        heading_score = -0.5 * (heading_delta / config.heading_sigma_deg) ** 2
        if edge.oneway and abs(heading_delta) > 120.0:
            heading_score -= config.one_way_opposition_log_penalty
        speed_score = _speed_class_score(speed_mps, edge.road_class)
        candidates.append(
            RoadCandidate(
                edge_id=edge.edge_id,
                projected_x_m=projection.x_m,
                projected_y_m=projection.y_m,
                along_m=projection.along_m,
                fraction=projection.fraction,
                distance_m=projection.distance_m,
                road_bearing_deg=projection.bearing_deg,
                road_class=edge.road_class,
                road_name=edge.road_name,
                oneway=edge.oneway,
                distance_log_score=distance_score,
                heading_log_score=heading_score,
                speed_class_log_score=speed_score,
                emission_log_score=distance_score + heading_score + speed_score,
            )
        )
    candidates.sort(key=lambda candidate: (-candidate.emission_log_score, candidate.edge_id))
    return candidates[: config.top_k_candidates], radius


def network_transition_distance_m(
    graph: LocalRoadGraph,
    previous: RoadCandidate,
    current: RoadCandidate,
    maximum_distance_m: float,
) -> float:
    previous_edge = graph.edges[previous.edge_id]
    current_edge = graph.edges[current.edge_id]
    if previous.edge_id == current.edge_id and current.along_m >= previous.along_m - 1.0:
        return abs(current.along_m - previous.along_m)
    remaining = previous_edge.length_m - previous.along_m
    beginning = current.along_m
    available = maximum_distance_m - remaining - beginning
    if available < 0:
        return math.inf
    middle = graph.shortest_node_distance_m(
        previous_edge.to_node, current_edge.from_node, available
    )
    if not np.isfinite(middle):
        return math.inf
    return float(remaining + middle + beginning)


def transition_log_score(
    graph: LocalRoadGraph,
    previous: RoadCandidate,
    current: RoadCandidate,
    expected_distance_m: float,
    yaw_change_deg: float,
    speed_mps: float,
    config: MapMatcherConfig,
) -> tuple[float, bool, float]:
    maximum = min(
        config.maximum_network_search_m,
        expected_distance_m + 5.0 * config.transition_distance_sigma_m + 25.0,
    )
    network_distance = network_transition_distance_m(graph, previous, current, maximum)
    if not np.isfinite(network_distance):
        return -config.impossible_transition_log_penalty, True, math.inf
    distance_scale = config.transition_distance_sigma_m
    if speed_mps <= config.stationary_speed_threshold_mps:
        distance_scale = min(distance_scale, config.stationary_motion_tolerance_m)
    distance_score = -0.5 * ((network_distance - expected_distance_m) / distance_scale) ** 2
    road_turn = angle_difference_deg(current.road_bearing_deg, previous.road_bearing_deg)
    turn_score = -0.5 * (angle_difference_deg(road_turn, yaw_change_deg) / config.turn_sigma_deg) ** 2
    switch_score = -config.edge_switch_log_penalty if current.edge_id != previous.edge_id else 0.0
    return float(distance_score + turn_score + switch_score), False, network_distance


def _normalized_probabilities(log_values: np.ndarray) -> np.ndarray:
    if log_values.size == 0:
        return np.empty(0, dtype=float)
    shifted = log_values - float(np.max(log_values))
    weights = np.exp(np.clip(shifted, -745.0, 0.0))
    total = float(np.sum(weights))
    return weights / total if total > 0 else np.full(len(weights), 1.0 / len(weights))


class ProbabilisticMapMatcher:
    """Causal road-candidate tracker with no reference, route, or destination API."""

    def __init__(self, graph: LocalRoadGraph, config: MapMatcherConfig):
        config.validate()
        self.graph = graph
        self.config = config

    def match(self, prior: pd.DataFrame, input_estimator: str) -> MapMatchResult:
        frame = _validate_runtime_prior(prior)
        records: list[dict[str, Any]] = []
        hypotheses: list[MapHypothesis] = []
        prior_xy = frame[["estimated_x_m", "estimated_y_m"]].to_numpy(dtype=float)
        candidate_seconds = 0.0
        matching_started = time.perf_counter()
        previous_yaw = float(frame["estimated_yaw_deg"].iloc[0])
        previous_elapsed = float(frame["elapsed_s"].iloc[0])
        previous_output_edge: str | None = None
        for index, row in frame.iterrows():
            started = time.perf_counter()
            candidates, radius = generate_candidates(
                self.graph,
                float(row["estimated_x_m"]),
                float(row["estimated_y_m"]),
                float(row["estimated_yaw_deg"]),
                float(row["estimated_speed_mps"]),
                float(row["horizontal_position_sigma_m"]),
                self.config,
            )
            candidate_seconds += time.perf_counter() - started
            dt = max(0.0, float(row["elapsed_s"]) - previous_elapsed)
            displacement = 0.0 if index == 0 else float(np.linalg.norm(prior_xy[index] - prior_xy[index - 1]))
            expected_distance = 0.5 * (
                displacement + max(0.0, float(row["estimated_speed_mps"])) * dt
            )
            yaw_change = angle_difference_deg(float(row["estimated_yaw_deg"]), previous_yaw)
            impossible_rejections = 0
            next_hypotheses: list[MapHypothesis] = []
            if candidates and hypotheses:
                for candidate in candidates:
                    best_score = -math.inf
                    best_predecessor: str | None = None
                    best_rejections = 0
                    for hypothesis in hypotheses:
                        transition_score, impossible, _ = transition_log_score(
                            self.graph,
                            hypothesis.candidate,
                            candidate,
                            expected_distance,
                            yaw_change,
                            float(row["estimated_speed_mps"]),
                            self.config,
                        )
                        impossible_rejections += int(impossible)
                        score = hypothesis.log_probability + transition_score + candidate.emission_log_score
                        if score > best_score:
                            best_score = score
                            best_predecessor = hypothesis.candidate.edge_id
                            best_rejections = hypothesis.impossible_transition_rejections + int(impossible)
                    next_hypotheses.append(
                        MapHypothesis(candidate, best_score, best_predecessor, best_rejections)
                    )
            elif candidates:
                next_hypotheses = [
                    MapHypothesis(candidate, candidate.emission_log_score, None) for candidate in candidates
                ]
            next_hypotheses.sort(key=lambda item: (-item.log_probability, item.candidate.edge_id))
            hypotheses = next_hypotheses[: self.config.beam_width]
            probabilities = _normalized_probabilities(
                np.array([item.log_probability for item in hypotheses], dtype=float)
            )
            top_probability = float(probabilities[0]) if len(probabilities) else 0.0
            second_probability = float(probabilities[1]) if len(probabilities) > 1 else 0.0
            gap = top_probability - second_probability
            if len(probabilities) > 1:
                entropy = float(-np.sum(probabilities * np.log(np.maximum(probabilities, 1e-300))))
                entropy_fraction = entropy / math.log(len(probabilities))
            else:
                entropy_fraction = 0.0
            top = hypotheses[0].candidate if hypotheses else None
            correction = top.distance_m if top is not None else 0.0
            apply = (
                top is not None
                and top_probability >= self.config.minimum_apply_probability
                and correction <= self.config.maximum_correction_m
            )
            if not candidates:
                status = "NO_CANDIDATE"
            elif not apply:
                status = "DEGRADED"
            elif gap < self.config.ambiguity_probability_gap or entropy_fraction > self.config.ambiguity_entropy_fraction:
                status = "AMBIGUOUS"
            else:
                status = "CONFIDENT"
            matched_x = float(top.projected_x_m) if apply and top is not None else float(row["estimated_x_m"])
            matched_y = float(top.projected_y_m) if apply and top is not None else float(row["estimated_y_m"])
            applied_correction = float(np.hypot(matched_x - row["estimated_x_m"], matched_y - row["estimated_y_m"]))
            edge_id = top.edge_id if top is not None else None
            road_switched = previous_output_edge is not None and edge_id is not None and edge_id != previous_output_edge
            records.append(
                {
                    "elapsed_s": float(row["elapsed_s"]),
                    "prior_east_m": float(row["estimated_x_m"]),
                    "prior_north_m": float(row["estimated_y_m"]),
                    "matched_east_m": matched_x,
                    "matched_north_m": matched_y,
                    "estimated_speed_mps": float(row["estimated_speed_mps"]),
                    "estimated_yaw_deg": float(row["estimated_yaw_deg"]),
                    "position_sigma_m": float(row["horizontal_position_sigma_m"]),
                    "candidate_search_radius_m": radius,
                    "road_edge_id": edge_id,
                    "road_name": top.road_name if top is not None else None,
                    "road_class": top.road_class if top is not None else None,
                    "road_bearing_deg": top.road_bearing_deg if top is not None else np.nan,
                    "top_probability": top_probability,
                    "second_probability": second_probability,
                    "ambiguity_score": float(1.0 - gap),
                    "hypothesis_entropy_fraction": entropy_fraction,
                    "candidate_count": len(candidates),
                    "retained_hypothesis_count": len(hypotheses),
                    "map_match_status": status,
                    "map_correction_m": applied_correction,
                    "impossible_transition_rejections": impossible_rejections,
                    "road_switch": road_switched,
                    "top_candidate_distance_m": top.distance_m if top is not None else np.nan,
                    "second_edge_id": hypotheses[1].candidate.edge_id if len(hypotheses) > 1 else None,
                    "second_candidate_distance_m": hypotheses[1].candidate.distance_m if len(hypotheses) > 1 else np.nan,
                }
            )
            previous_yaw = float(row["estimated_yaw_deg"])
            previous_elapsed = float(row["elapsed_s"])
            if edge_id is not None:
                previous_output_edge = edge_id
        output = pd.DataFrame(records)
        latitude, longitude = local_xy_to_geodetic(
            output["matched_east_m"],
            output["matched_north_m"],
            self.graph.origin_latitude_deg,
            self.graph.origin_longitude_deg,
        )
        output["matched_latitude_deg"] = latitude
        output["matched_longitude_deg"] = longitude
        return MapMatchResult(
            data=output,
            candidate_generation_seconds=candidate_seconds,
            matching_seconds=time.perf_counter() - matching_started,
            input_estimator=input_estimator,
        )


def nearest_road_match(
    prior: pd.DataFrame,
    graph: LocalRoadGraph,
    config: MapMatcherConfig,
    input_estimator: str,
) -> MapMatchResult:
    """Deliberately naive independent nearest-edge baseline."""

    frame = _validate_runtime_prior(prior)
    records: list[dict[str, Any]] = []
    candidate_seconds = 0.0
    started_all = time.perf_counter()
    previous_edge: str | None = None
    for _, row in frame.iterrows():
        started = time.perf_counter()
        radius = config.search_radius_m(float(row["horizontal_position_sigma_m"]))
        nearest: tuple[float, LocalRoadEdge, Any] | None = None
        for edge_id in graph.nearby_edge_ids(float(row["estimated_x_m"]), float(row["estimated_y_m"]), radius):
            edge = graph.edges[edge_id]
            try:
                projection = project_onto_polyline(
                    (float(row["estimated_x_m"]), float(row["estimated_y_m"])), edge.points_xy_m
                )
            except ValueError:
                continue
            if projection.distance_m <= radius and (nearest is None or projection.distance_m < nearest[0]):
                nearest = (projection.distance_m, edge, projection)
        candidate_seconds += time.perf_counter() - started
        apply = nearest is not None and nearest[0] <= config.maximum_correction_m
        edge = nearest[1] if nearest is not None else None
        projection = nearest[2] if nearest is not None else None
        edge_id = edge.edge_id if edge is not None else None
        records.append(
            {
                "elapsed_s": float(row["elapsed_s"]),
                "prior_east_m": float(row["estimated_x_m"]),
                "prior_north_m": float(row["estimated_y_m"]),
                "matched_east_m": projection.x_m if apply else float(row["estimated_x_m"]),
                "matched_north_m": projection.y_m if apply else float(row["estimated_y_m"]),
                "estimated_speed_mps": float(row["estimated_speed_mps"]),
                "estimated_yaw_deg": float(row["estimated_yaw_deg"]),
                "position_sigma_m": float(row["horizontal_position_sigma_m"]),
                "candidate_search_radius_m": radius,
                "road_edge_id": edge_id,
                "road_name": edge.road_name if edge is not None else None,
                "road_class": edge.road_class if edge is not None else None,
                "road_bearing_deg": projection.bearing_deg if projection is not None else np.nan,
                "top_probability": 1.0 if apply else 0.0,
                "second_probability": 0.0,
                "ambiguity_score": 0.0 if apply else 1.0,
                "hypothesis_entropy_fraction": 0.0,
                "candidate_count": 1 if nearest is not None else 0,
                "retained_hypothesis_count": 1 if nearest is not None else 0,
                "map_match_status": "CONFIDENT" if apply else ("DEGRADED" if nearest else "NO_CANDIDATE"),
                "map_correction_m": nearest[0] if apply else 0.0,
                "impossible_transition_rejections": 0,
                "road_switch": previous_edge is not None and edge_id is not None and edge_id != previous_edge,
                "top_candidate_distance_m": nearest[0] if nearest is not None else np.nan,
                "second_edge_id": None,
                "second_candidate_distance_m": np.nan,
            }
        )
        if edge_id is not None:
            previous_edge = edge_id
    output = pd.DataFrame(records)
    latitude, longitude = local_xy_to_geodetic(
        output["matched_east_m"], output["matched_north_m"],
        graph.origin_latitude_deg, graph.origin_longitude_deg,
    )
    output["matched_latitude_deg"] = latitude
    output["matched_longitude_deg"] = longitude
    return MapMatchResult(
        data=output,
        candidate_generation_seconds=candidate_seconds,
        matching_seconds=time.perf_counter() - started_all,
        input_estimator=input_estimator,
        algorithm="phase6_naive_nearest_road_v1",
    )


def matcher_api_is_reference_free() -> bool:
    """Machine-testable documentation of the estimator/evaluator boundary."""

    parameters = inspect.signature(ProbabilisticMapMatcher.match).parameters
    return "reference" not in parameters and "route" not in parameters and "destination" not in parameters
