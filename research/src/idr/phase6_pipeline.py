"""Runtime/evaluation orchestration for one Phase 6 blackout scenario."""

from __future__ import annotations

import time
from dataclasses import dataclass

from .blackout import BlackoutWindow
from .calibrated_dr import Phase4Settings
from .hybrid.hybrid_idr import HybridSettings
from .io_vnbd import IOVNBDJourney
from .map_matching.evaluation import MapMatchEvaluation, evaluate_map_match
from .map_matching.matcher import (
    MapMatchResult,
    MapMatcherConfig,
    ProbabilisticMapMatcher,
    nearest_road_match,
)
from .map_matching.road_graph import RoadGraph
from .map_matching.road_graph import LocalRoadGraph
from .ml.velocity_model import VelocityModelBundle
from .phase5_pipeline import Phase5ScenarioRun, run_phase5_scenario


@dataclass(frozen=True)
class Phase6ScenarioRun:
    phase5: Phase5ScenarioRun
    local_road_graph: LocalRoadGraph
    ekf_nearest: MapMatchResult
    hybrid_nearest: MapMatchResult
    ekf_probabilistic: MapMatchResult
    hybrid_probabilistic: MapMatchResult
    ekf_nearest_evaluation: MapMatchEvaluation
    hybrid_nearest_evaluation: MapMatchEvaluation
    ekf_probabilistic_evaluation: MapMatchEvaluation
    hybrid_probabilistic_evaluation: MapMatchEvaluation
    road_graph_localization_seconds: float


def run_phase6_scenario(
    journey: IOVNBDJourney,
    window: BlackoutWindow,
    phase4_settings: Phase4Settings,
    hybrid_settings: HybridSettings,
    model_bundle: VelocityModelBundle,
    road_graph: RoadGraph,
    map_settings: MapMatcherConfig,
) -> Phase6ScenarioRun:
    """Run both Phase 5 priors, then match before reference evaluation."""

    phase5 = run_phase5_scenario(
        journey, window, phase4_settings, hybrid_settings, model_bundle
    )
    initialization = phase5.ekf_prediction.calibration.initialization
    started = time.perf_counter()
    local_graph = road_graph.localize(
        initialization.origin_latitude_deg,
        initialization.origin_longitude_deg,
        map_settings.grid_cell_size_m,
    )
    localization_seconds = time.perf_counter() - started
    matcher = ProbabilisticMapMatcher(local_graph, map_settings)
    ekf_nearest = nearest_road_match(
        phase5.ekf_prediction.data, local_graph, map_settings, "E1_EKF_CLASSICAL"
    )
    hybrid_nearest = nearest_road_match(
        phase5.hybrid_prediction.data, local_graph, map_settings, "H1_HYBRID_EKF_ML"
    )
    ekf_probabilistic = matcher.match(
        phase5.ekf_prediction.data, "E1_EKF_CLASSICAL"
    )
    hybrid_probabilistic = matcher.match(
        phase5.hybrid_prediction.data, "H1_HYBRID_EKF_ML"
    )
    # Only this block crosses into the evaluation-only VBOX reference.
    reference = phase5.experiment.reference
    return Phase6ScenarioRun(
        phase5=phase5,
        local_road_graph=local_graph,
        ekf_nearest=ekf_nearest,
        hybrid_nearest=hybrid_nearest,
        ekf_probabilistic=ekf_probabilistic,
        hybrid_probabilistic=hybrid_probabilistic,
        ekf_nearest_evaluation=evaluate_map_match(
            ekf_nearest, phase5.ekf_prediction, reference
        ),
        hybrid_nearest_evaluation=evaluate_map_match(
            hybrid_nearest, phase5.hybrid_prediction, reference
        ),
        ekf_probabilistic_evaluation=evaluate_map_match(
            ekf_probabilistic, phase5.ekf_prediction, reference
        ),
        hybrid_probabilistic_evaluation=evaluate_map_match(
            hybrid_probabilistic, phase5.hybrid_prediction, reference
        ),
        road_graph_localization_seconds=localization_seconds,
    )
