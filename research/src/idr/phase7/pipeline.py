"""Reference-free Phase 7 runtime composition and separate offline evaluation."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from ..blackout import BlackoutWindow, EvaluationReference, RuntimeDataset
from ..calibrated_dr import Phase4Settings, build_phase4_calibration
from ..evaluation import (
    drift_percentage,
    geodetic_to_local_xy_m,
    local_xy_to_geodetic,
    path_distance_m,
    position_error_series_m,
)
from ..hybrid.hybrid_idr import HybridPrediction, HybridSettings, run_hybrid_estimator
from ..map_matching.matcher import MapMatcherConfig, ProbabilisticMapMatcher
from ..map_matching.road_graph import LocalRoadGraph, RoadGraph
from ..ml.velocity_model import VelocityModelBundle
from .config import Phase7Config
from .engine import NavigationInput, NavigationState, ReacquisitionEngine
from .gnss import GNSSClassification, GNSSObservation


@dataclass(frozen=True)
class Phase7RuntimeRun:
    """Runtime-only output. This type deliberately contains no reference data."""

    window: BlackoutWindow
    data: pd.DataFrame
    phase5_prediction: HybridPrediction
    local_road_graph: LocalRoadGraph
    transitions: tuple[dict[str, Any], ...]
    startup_seconds: dict[str, float]
    online_latency_ms: np.ndarray
    origin_latitude_deg: float
    origin_longitude_deg: float


@dataclass(frozen=True)
class Phase7Evaluation:
    """Offline metrics created only after the runtime computation is complete."""

    metrics: dict[str, Any]
    timeseries: pd.DataFrame


def _observation_lookup(frame: pd.DataFrame) -> dict[float, GNSSObservation]:
    return {
        round(float(row["elapsed_s"]), 6): GNSSObservation.from_mapping(row)
        for _, row in frame.iterrows()
    }


def _hard_snap_track(
    frame: pd.DataFrame,
    snap_index: int | None,
    origin_latitude_deg: float,
    origin_longitude_deg: float,
) -> tuple[np.ndarray, float | None]:
    xy = frame[["idr_east_m", "idr_north_m"]].to_numpy(dtype=float).copy()
    if snap_index is None:
        return xy, None
    latitude = frame["phone_gnss_latitude_deg"].to_numpy(dtype=float)
    longitude = frame["phone_gnss_longitude_deg"].to_numpy(dtype=float)
    valid = np.isfinite(latitude) & np.isfinite(longitude)
    gnss_xy = np.full_like(xy, np.nan)
    if valid.any():
        local = geodetic_to_local_xy_m(
            latitude[valid], longitude[valid], origin_latitude_deg, origin_longitude_deg
        )
        gnss_xy[valid] = np.column_stack((local.x_east_m, local.y_north_m))
    last = None
    for index in range(snap_index, len(frame)):
        if valid[index]:
            last = gnss_xy[index]
        if last is not None:
            xy[index] = last
    jump = float(
        np.linalg.norm(
            gnss_xy[snap_index]
            - frame.loc[snap_index, ["idr_east_m", "idr_north_m"]].to_numpy(dtype=float)
        )
    )
    return xy, jump


def run_phase7_runtime(
    runtime: RuntimeDataset,
    window: BlackoutWindow,
    phase4_settings: Phase4Settings,
    hybrid_settings: HybridSettings,
    model_bundle: VelocityModelBundle,
    road_graph: RoadGraph,
    map_settings: MapMatcherConfig,
    phase7_settings: Phase7Config,
    *,
    enabled: bool = True,
) -> Phase7RuntimeRun:
    """Run the causal phone/IDR pipeline; no VBOX/reference argument is accepted."""

    phase7_settings.validate()
    overall = time.perf_counter()
    sensor = runtime.sensor_data
    gnss = runtime.gnss_observations
    sensor_history = sensor.loc[sensor["elapsed_s"] < window.start_s].copy()
    gnss_history = gnss.loc[gnss["elapsed_s"] < window.start_s].copy()
    calibration = build_phase4_calibration(sensor_history, gnss_history, window.start_s, phase4_settings)
    phone_accuracy = float(gnss_history["gps_accuracy_m"].iloc[-1])
    origin_lat = calibration.initialization.origin_latitude_deg
    origin_lon = calibration.initialization.origin_longitude_deg
    tail_end = min(
        window.end_s + phase7_settings.post_blackout_tail_s,
        float(sensor["elapsed_s"].iloc[-1]) + 1e-9,
    )
    span = sensor.loc[
        (sensor["elapsed_s"] >= window.start_s) & (sensor["elapsed_s"] < tail_end)
    ].copy().reset_index(drop=True)
    # Keep the IDR backend warm after signal return. Its input is an explicitly
    # GNSS-free sensor view; returned GNSS is handled only by the Phase 7 engine.
    span["gnss_available"] = False

    started = time.perf_counter()
    phase5 = run_hybrid_estimator(
        span,
        calibration,
        phase4_settings,
        hybrid_settings,
        model_bundle,
        phone_gnss_accuracy_m=phone_accuracy,
    )
    phase5_seconds = time.perf_counter() - started
    started = time.perf_counter()
    local_graph = road_graph.localize(origin_lat, origin_lon, map_settings.grid_cell_size_m)
    localization_seconds = time.perf_counter() - started
    blackout_count = int((span["elapsed_s"] < window.end_s).sum())
    started = time.perf_counter()
    matched = ProbabilisticMapMatcher(local_graph, map_settings).match(
        phase5.data.iloc[:blackout_count].reset_index(drop=True), "H1_HYBRID_EKF_ML"
    )
    map_seconds = time.perf_counter() - started

    prior = phase5.data.reset_index(drop=True)
    idr_xy = prior[["estimated_x_m", "estimated_y_m"]].to_numpy(dtype=float).copy()
    matched_xy = matched.data[["matched_east_m", "matched_north_m"]].to_numpy(dtype=float)
    idr_xy[:blackout_count] = matched_xy
    if blackout_count < len(idr_xy):
        carry = (
            matched_xy[-1]
            - prior.loc[
                blackout_count - 1, ["estimated_x_m", "estimated_y_m"]
            ].to_numpy(dtype=float)
        )
        idr_xy[blackout_count:] += carry

    lookup = _observation_lookup(gnss)
    engine = ReacquisitionEngine(phase7_settings, origin_lat, origin_lon, enabled=enabled)
    prime = gnss_history.loc[gnss_history["elapsed_s"] >= window.start_s - 120.0]
    for _, row in prime.iterrows():
        engine.prime_gnss(GNSSObservation.from_mapping(row))

    rows: list[dict[str, Any]] = []
    latencies: list[float] = []
    for index, row in span.iterrows():
        elapsed = float(row["elapsed_s"])
        observation = lookup.get(round(elapsed, 6), GNSSObservation.missing(elapsed))
        output = engine.step(
            NavigationInput(
                elapsed_s=elapsed,
                idr_east_m=float(idr_xy[index, 0]),
                idr_north_m=float(idr_xy[index, 1]),
                idr_speed_mps=float(prior["estimated_speed_mps"].iloc[index]),
                idr_yaw_deg=float(prior["estimated_yaw_deg"].iloc[index]),
                idr_position_sigma_m=float(prior["horizontal_position_sigma_m"].iloc[index]),
                gnss=observation,
            )
        )
        record = output.to_dict()
        record.update(
            {
                "idr_east_m": float(idr_xy[index, 0]),
                "idr_north_m": float(idr_xy[index, 1]),
                "idr_speed_mps": float(prior["estimated_speed_mps"].iloc[index]),
                "idr_yaw_deg": float(prior["estimated_yaw_deg"].iloc[index]),
                "idr_position_sigma_m": float(prior["horizontal_position_sigma_m"].iloc[index]),
                "is_blackout": bool(elapsed < window.end_s),
                "phone_gnss_latitude_deg": observation.latitude_deg,
                "phone_gnss_longitude_deg": observation.longitude_deg,
            }
        )
        rows.append(record)
        latencies.append(output.online_latency_ms)
    data = pd.DataFrame(rows)
    returned = np.flatnonzero(
        (data["elapsed_s"].to_numpy(dtype=float) >= window.end_s)
        & np.isfinite(data["phone_gnss_latitude_deg"].to_numpy(dtype=float))
    )
    fresh = np.flatnonzero(
        (data["elapsed_s"].to_numpy(dtype=float) >= window.end_s)
        & (data["gnss_classification"].to_numpy(dtype=str) == GNSSClassification.FRESH.value)
    )
    b0_xy, b0_jump = _hard_snap_track(
        data, int(returned[0]) if returned.size else None, origin_lat, origin_lon
    )
    b1_xy, b1_jump = _hard_snap_track(
        data, int(fresh[0]) if fresh.size else None, origin_lat, origin_lon
    )
    data["b0_east_m"], data["b0_north_m"] = b0_xy[:, 0], b0_xy[:, 1]
    data["b1_east_m"], data["b1_north_m"] = b1_xy[:, 0], b1_xy[:, 1]
    data.attrs["b0_jump_m"] = b0_jump
    data.attrs["b1_jump_m"] = b1_jump
    return Phase7RuntimeRun(
        window=window,
        data=data,
        phase5_prediction=phase5,
        local_road_graph=local_graph,
        transitions=tuple(engine.transition_history),
        startup_seconds={
            "phase5_span_processing": phase5_seconds,
            "road_graph_localization": localization_seconds,
            "phase6_blackout_map_matching": map_seconds,
            "runtime_total_excluding_evaluation": time.perf_counter() - overall,
        },
        online_latency_ms=np.asarray(latencies, dtype=float),
        origin_latitude_deg=origin_lat,
        origin_longitude_deg=origin_lon,
    )


def _first_time(frame: pd.DataFrame, mask: np.ndarray) -> float | None:
    indices = np.flatnonzero(mask)
    return None if not indices.size else float(frame["elapsed_s"].iloc[int(indices[0])])


def evaluate_phase7_runtime(
    run: Phase7RuntimeRun, reference: EvaluationReference
) -> Phase7Evaluation:
    """Evaluate a completed runtime trajectory against hidden synchronized VBOX."""

    frame = run.data.copy().reset_index(drop=True)
    attrs = dict(run.data.attrs)
    reference_frame = (
        reference.data.set_index("runtime_elapsed_s").loc[frame["elapsed_s"]].reset_index()
    )
    ref_lat = reference_frame["latitude_deg"].to_numpy(dtype=float)
    ref_lon = reference_frame["longitude_deg"].to_numpy(dtype=float)
    ref_local = geodetic_to_local_xy_m(
        ref_lat, ref_lon, run.origin_latitude_deg, run.origin_longitude_deg
    )
    ref_xy = np.column_stack((ref_local.x_east_m, ref_local.y_north_m))
    elapsed = frame["elapsed_s"].to_numpy(dtype=float)
    blackout = elapsed < run.window.end_s
    post = ~blackout
    idr_xy = frame[["idr_east_m", "idr_north_m"]].to_numpy(dtype=float)
    blackout_errors = np.linalg.norm(
        (idr_xy[blackout] - idr_xy[blackout][0])
        - (ref_xy[blackout] - ref_xy[blackout][0]),
        axis=1,
    )
    blackout_reference_distance = path_distance_m(ref_lat[blackout], ref_lon[blackout])
    frame["reference_latitude_deg"] = ref_lat
    frame["reference_longitude_deg"] = ref_lon
    frame["p7_absolute_error_m"] = position_error_series_m(
        frame["navigation_latitude_deg"], frame["navigation_longitude_deg"], ref_lat, ref_lon
    )
    for prefix in ("b0", "b1"):
        latitude, longitude = local_xy_to_geodetic(
            frame[f"{prefix}_east_m"], frame[f"{prefix}_north_m"],
            run.origin_latitude_deg, run.origin_longitude_deg,
        )
        frame[f"{prefix}_absolute_error_m"] = position_error_series_m(
            latitude, longitude, ref_lat, ref_lon
        )
    frame["blackout_relative_idr_error_m"] = np.nan
    frame.loc[blackout, "blackout_relative_idr_error_m"] = blackout_errors

    fresh_post = post & (
        frame["gnss_classification"].to_numpy(dtype=str) == GNSSClassification.FRESH.value
    )
    first_fresh_time = _first_time(frame, fresh_post)
    recovering = post & (
        frame["navigation_state"].to_numpy(dtype=str) == NavigationState.GNSS_RECOVERING.value
    )
    recovery_start = _first_time(frame, recovering)
    active_after_recovery = np.zeros(len(frame), dtype=bool)
    if recovery_start is not None:
        active_after_recovery = (elapsed > recovery_start) & (
            frame["navigation_state"].to_numpy(dtype=str) == NavigationState.GNSS_ACTIVE.value
        )
    active_time = _first_time(frame, active_after_recovery)
    evaluation_start = recovery_start if recovery_start is not None else first_fresh_time
    evaluation_mask = post if evaluation_start is None else elapsed >= evaluation_start
    errors = frame.loc[evaluation_mask, "p7_absolute_error_m"].to_numpy(dtype=float)
    decisions = frame["gnss_decision"].astype(str)
    columns = [
        "elapsed_s", "gnss_innovation_m", "innovation_gate_m",
        "innovation_within_gate", "gnss_decision",
    ]
    accepted = frame.loc[
        post & decisions.str.contains("accepted|verified", regex=True), columns
    ]
    rejected = frame.loc[post & decisions.str.contains("rejected", regex=False), columns]
    metrics: dict[str, Any] = {
        "blackout_duration_s": run.window.duration_s,
        "blackout_final_idr_error_m": float(blackout_errors[-1]),
        "blackout_reference_distance_m": blackout_reference_distance,
        "blackout_final_idr_drift_pct": drift_percentage(float(blackout_errors[-1]), blackout_reference_distance),
        "blackout_end_s": run.window.end_s,
        "first_genuinely_fresh_fix_s": first_fresh_time,
        "fresh_fix_delay_after_blackout_s": None if first_fresh_time is None else first_fresh_time - run.window.end_s,
        "stale_repeated_fixes_rejected": int((post & (frame["gnss_classification"] == GNSSClassification.REPEATED.value)).sum()),
        "candidate_reacquisition_fixes_rejected": int((post & decisions.str.contains("candidate_rejected", regex=False)).sum()),
        "fresh_fixes_required_before_verification": int(frame["verification_fresh_fix_count"].max()),
        "b0_first_returned_coordinate_hard_snap_jump_m": attrs.get("b0_jump_m"),
        "b1_first_fresh_fix_hard_snap_jump_m": attrs.get("b1_jump_m"),
        "phase7_maximum_instantaneous_correction_m": float(frame["correction_applied_m"].max()),
        "maximum_recovery_correction_rate_mps": float(frame["correction_rate_mps"].max()),
        "recovery_start_s": recovery_start,
        "recovery_duration_s": None if active_time is None or recovery_start is None else active_time - recovery_start,
        "time_to_return_gnss_active_s": None if active_time is None else active_time - run.window.end_s,
        "post_reacquisition_rmse_m": None if not errors.size else float(np.sqrt(np.mean(np.square(errors)))),
        "post_reacquisition_p95_m": None if not errors.size else float(np.percentile(errors, 95)),
        "final_post_recovery_error_m": float(frame.loc[post, "p7_absolute_error_m"].iloc[-1]),
        "state_transition_sequence": [item["to"] for item in run.transitions],
        "state_transitions": list(run.transitions),
        "accepted_innovations": accepted.replace({np.nan: None}).to_dict(orient="records"),
        "rejected_innovations": rejected.replace({np.nan: None}).to_dict(orient="records"),
        "uncertainty_before_recovery_m": None if recovery_start is None else float(frame.loc[elapsed < recovery_start, "navigation_uncertainty_m"].iloc[-1]),
        "uncertainty_after_recovery_m": float(frame.loc[post, "navigation_uncertainty_m"].iloc[-1]),
        "warm_online_average_ms_per_sample": float(np.mean(run.online_latency_ms)),
        "warm_online_p50_ms": float(np.percentile(run.online_latency_ms, 50)),
        "warm_online_p95_ms": float(np.percentile(run.online_latency_ms, 95)),
        "warm_online_p99_ms": float(np.percentile(run.online_latency_ms, 99)),
        "warm_online_samples_per_second": float(1000.0 / np.mean(run.online_latency_ms)),
    }
    return Phase7Evaluation(metrics, frame)
