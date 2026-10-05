"""Evaluation-only utilities for Phase 6 map-matched predictions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from ..blackout import EvaluationReference
from ..dead_reckoning import RawDRPrediction
from ..hybrid.hybrid_idr import HybridPrediction
from ..raw_dr_evaluation import RawDREvaluation, evaluate_raw_dr_prediction
from .matcher import MapMatchResult


@dataclass(frozen=True)
class MapMatchEvaluation:
    metrics: dict[str, Any]
    timeseries: pd.DataFrame


def as_raw_map_prediction(
    match: MapMatchResult,
    prior: HybridPrediction,
) -> RawDRPrediction:
    """Adapt map output to the established relative-position evaluator."""

    if len(match.data) != len(prior.data) or not np.array_equal(
        match.data["elapsed_s"].to_numpy(dtype=float),
        prior.data["elapsed_s"].to_numpy(dtype=float),
    ):
        raise ValueError("Map-match output and Phase 5 prior are not aligned.")
    output = prior.data.copy().reset_index(drop=True)
    output["estimated_x_m"] = match.data["matched_east_m"].to_numpy(dtype=float)
    output["estimated_y_m"] = match.data["matched_north_m"].to_numpy(dtype=float)
    output["estimated_latitude_deg"] = match.data["matched_latitude_deg"].to_numpy(dtype=float)
    output["estimated_longitude_deg"] = match.data["matched_longitude_deg"].to_numpy(dtype=float)
    return RawDRPrediction(
        data=output,
        initialization=prior.calibration.initialization,
        algorithm=match.algorithm,
    )


def evaluate_map_match(
    match: MapMatchResult,
    prior: HybridPrediction,
    reference: EvaluationReference,
) -> MapMatchEvaluation:
    """Cross the hidden-reference boundary only after matching has completed."""

    base: RawDREvaluation = evaluate_raw_dr_prediction(
        as_raw_map_prediction(match, prior), reference
    )
    diagnostics = match.data.reset_index(drop=True)
    correction = diagnostics["map_correction_m"].to_numpy(dtype=float)
    candidate_count = diagnostics["candidate_count"].to_numpy(dtype=int)
    status = diagnostics["map_match_status"].astype(str)
    road_ids = diagnostics["road_edge_id"].astype(object)
    valid_road = road_ids.notna().to_numpy(dtype=bool)
    road_switches = 0
    previous: str | None = None
    for road_id, valid in zip(road_ids, valid_road, strict=True):
        if not valid:
            continue
        value = str(road_id)
        road_switches += int(previous is not None and value != previous)
        previous = value
    metrics: dict[str, Any] = {
        **base.metrics,
        "matched_road_correctness_available": False,
        "matched_road_correctness_note": "Unavailable: IO-VNBD supplies no ground-truth OSM edge IDs.",
        "mean_map_correction_m": float(np.mean(correction)),
        "maximum_map_correction_m": float(np.max(correction)),
        "corrections_above_10m": int(np.count_nonzero(correction > 10.0)),
        "corrections_above_25m": int(np.count_nonzero(correction > 25.0)),
        "corrections_above_50m": int(np.count_nonzero(correction > 50.0)),
        "road_switch_count": int(road_switches),
        "hypothesis_switch_count": int(np.count_nonzero(diagnostics["road_switch"])),
        "no_candidate_count": int(np.count_nonzero(status == "NO_CANDIDATE")),
        "no_candidate_fraction": float(np.mean(status == "NO_CANDIDATE")),
        "ambiguous_sample_count": int(np.count_nonzero(status == "AMBIGUOUS")),
        "ambiguous_sample_fraction": float(np.mean(status == "AMBIGUOUS")),
        "degraded_sample_count": int(np.count_nonzero(status == "DEGRADED")),
        "mean_top_candidate_probability": float(diagnostics["top_probability"].mean()),
        "mean_candidate_count": float(np.mean(candidate_count)),
        "maximum_candidate_count": int(np.max(candidate_count)),
        "mean_candidate_search_radius_m": float(diagnostics["candidate_search_radius_m"].mean()),
        "maximum_candidate_search_radius_m": float(diagnostics["candidate_search_radius_m"].max()),
        "impossible_transition_rejections": int(diagnostics["impossible_transition_rejections"].sum()),
        "candidate_generation_samples_per_second": float(
            len(diagnostics) / max(match.candidate_generation_seconds, 1e-12)
        ),
        "map_matching_samples_per_second": float(
            len(diagnostics) / max(match.matching_seconds, 1e-12)
        ),
    }
    timeseries = base.timeseries.copy()
    for column in diagnostics.columns:
        if column == "elapsed_s" or column in timeseries.columns:
            continue
        timeseries[column] = diagnostics[column].to_numpy()
    return MapMatchEvaluation(metrics, timeseries)
