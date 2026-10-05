"""Offline-only Phase 5 development sequence construction.

This module is deliberately separate from runtime inference because it is the
only Phase 5 feature-preparation code allowed to access VBOX velocity labels.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .blackout import BlackoutWindow, create_blackout_experiment
from .calibrated_dr import Phase4Settings, build_phase4_calibration
from .dead_reckoning import extract_blackout_sensor_data
from .hybrid.hybrid_idr import HybridSettings, run_hybrid_estimator
from .io_vnbd import IOVNBDJourney


@dataclass(frozen=True)
class DevelopmentSequence:
    interval_id: str
    start_s: float
    end_s: float
    features: pd.DataFrame
    elapsed_s: np.ndarray
    classical_speed_mps: np.ndarray
    reference_speed_mps: np.ndarray
    target_residual_mps: np.ndarray


def build_development_sequence(
    journey: IOVNBDJourney,
    interval: dict[str, object],
    phase4_settings: Phase4Settings,
    hybrid_settings: HybridSettings,
) -> DevelopmentSequence:
    """Run a reference-free E1 sequence, then attach offline speed labels."""

    start = float(interval["start_s"])
    end = float(interval["end_s"])
    experiment = create_blackout_experiment(journey, BlackoutWindow(start, end - start))
    runtime = experiment.runtime.sensor_data
    sensor_history = runtime.loc[runtime["elapsed_s"] < start].copy()
    gnss_history = experiment.runtime.gnss_observations.loc[
        experiment.runtime.gnss_observations["elapsed_s"] < start
    ].copy()
    if sensor_history.empty or gnss_history.empty:
        raise ValueError(f"Development interval {interval['id']} lacks causal initialization history.")
    calibration = build_phase4_calibration(
        sensor_history, gnss_history, start, phase4_settings
    )
    blackout = extract_blackout_sensor_data(experiment.runtime, BlackoutWindow(start, end - start))
    accuracy = float(gnss_history["gps_accuracy_m"].iloc[-1])
    # Runtime estimator completes before the evaluation reference is touched.
    prediction = run_hybrid_estimator(
        blackout,
        calibration,
        phase4_settings,
        hybrid_settings,
        model_bundle=None,
        phone_gnss_accuracy_m=accuracy,
    )
    reference = experiment.reference.data.loc[experiment.reference.data["is_blackout"]]
    reference_speed = reference["velocity_kmh"].to_numpy(dtype=float) / 3.6
    elapsed = prediction.data["elapsed_s"].to_numpy(dtype=float)
    reference_elapsed = reference["runtime_elapsed_s"].to_numpy(dtype=float)
    if not np.array_equal(elapsed, reference_elapsed):
        raise ValueError("Offline label timestamps do not align with runtime features.")
    classical = prediction.data["estimated_speed_mps"].to_numpy(dtype=float)
    return DevelopmentSequence(
        interval_id=str(interval["id"]),
        start_s=start,
        end_s=end,
        features=prediction.feature_data,
        elapsed_s=elapsed,
        classical_speed_mps=classical,
        reference_speed_mps=reference_speed,
        target_residual_mps=reference_speed - classical,
    )
