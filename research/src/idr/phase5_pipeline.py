"""Offline experiment orchestration around the isolated Phase 5 estimator."""

from __future__ import annotations

import time
from dataclasses import dataclass

from .blackout import BlackoutWindow, ExperimentDataset, create_blackout_experiment
from .calibrated_dr import (
    CalibratedDRPrediction,
    Phase4Settings,
    as_raw_prediction,
    build_phase4_calibration,
    integrate_calibrated_dead_reckoning,
)
from .dead_reckoning import (
    RawDRPrediction,
    build_phone_initialization,
    extract_blackout_sensor_data,
    integrate_raw_dead_reckoning,
)
from .hybrid.hybrid_idr import (
    HybridEvaluation,
    HybridPrediction,
    HybridSettings,
    evaluate_hybrid_prediction,
    run_hybrid_estimator,
)
from .io_vnbd import IOVNBDJourney
from .ml.velocity_model import VelocityModelBundle
from .raw_dr_evaluation import RawDREvaluation, evaluate_raw_dr_prediction


@dataclass(frozen=True)
class Phase5ScenarioRun:
    experiment: ExperimentDataset
    blackout_sensor_data: object
    raw_prediction: RawDRPrediction
    phase4_v4_prediction: CalibratedDRPrediction
    phase4_v5_prediction: CalibratedDRPrediction
    ekf_prediction: HybridPrediction
    hybrid_prediction: HybridPrediction
    raw_evaluation: RawDREvaluation
    phase4_v4_evaluation: RawDREvaluation
    phase4_v5_evaluation: RawDREvaluation
    ekf_evaluation: HybridEvaluation
    hybrid_evaluation: HybridEvaluation
    processing_seconds: dict[str, float]


def run_phase5_scenario(
    journey: IOVNBDJourney,
    window: BlackoutWindow,
    phase4_settings: Phase4Settings,
    hybrid_settings: HybridSettings,
    model_bundle: VelocityModelBundle,
) -> Phase5ScenarioRun:
    """Complete all predictions before passing them to offline evaluators."""

    experiment = create_blackout_experiment(journey, window)
    sensor = experiment.runtime.sensor_data
    gnss = experiment.runtime.gnss_observations
    sensor_history = sensor.loc[sensor["elapsed_s"] < window.start_s].copy()
    gnss_history = gnss.loc[gnss["elapsed_s"] < window.start_s].copy()
    blackout = extract_blackout_sensor_data(experiment.runtime, window)
    raw_initialization = build_phone_initialization(sensor_history, gnss_history, window.start_s)
    calibration = build_phase4_calibration(
        sensor_history, gnss_history, window.start_s, phase4_settings
    )
    phone_accuracy = float(gnss_history["gps_accuracy_m"].iloc[-1])

    predictions: dict[str, object] = {}
    seconds: dict[str, float] = {}
    started = time.perf_counter()
    predictions["raw"] = integrate_raw_dead_reckoning(blackout, raw_initialization)
    seconds["raw"] = time.perf_counter() - started
    for key, variant in (("phase4_v4", "V4_MOTION_AWARE"), ("phase4_v5", "V5_PHASE4_COMBINED")):
        started = time.perf_counter()
        predictions[key] = integrate_calibrated_dead_reckoning(
            blackout, calibration, phase4_settings, variant
        )
        seconds[key] = time.perf_counter() - started
    started = time.perf_counter()
    predictions["ekf"] = run_hybrid_estimator(
        blackout,
        calibration,
        phase4_settings,
        hybrid_settings,
        model_bundle=None,
        phone_gnss_accuracy_m=phone_accuracy,
    )
    seconds["ekf"] = time.perf_counter() - started
    started = time.perf_counter()
    predictions["hybrid"] = run_hybrid_estimator(
        blackout,
        calibration,
        phase4_settings,
        hybrid_settings,
        model_bundle=model_bundle,
        phone_gnss_accuracy_m=phone_accuracy,
    )
    seconds["hybrid"] = time.perf_counter() - started

    raw_prediction = predictions["raw"]
    phase4_v4_prediction = predictions["phase4_v4"]
    phase4_v5_prediction = predictions["phase4_v5"]
    ekf_prediction = predictions["ekf"]
    hybrid_prediction = predictions["hybrid"]
    assert isinstance(raw_prediction, RawDRPrediction)
    assert isinstance(phase4_v4_prediction, CalibratedDRPrediction)
    assert isinstance(phase4_v5_prediction, CalibratedDRPrediction)
    assert isinstance(ekf_prediction, HybridPrediction)
    assert isinstance(hybrid_prediction, HybridPrediction)
    # The EvaluationReference boundary is crossed only here, after all
    # estimators have completed without it.
    return Phase5ScenarioRun(
        experiment=experiment,
        blackout_sensor_data=blackout,
        raw_prediction=raw_prediction,
        phase4_v4_prediction=phase4_v4_prediction,
        phase4_v5_prediction=phase4_v5_prediction,
        ekf_prediction=ekf_prediction,
        hybrid_prediction=hybrid_prediction,
        raw_evaluation=evaluate_raw_dr_prediction(raw_prediction, experiment.reference),
        phase4_v4_evaluation=evaluate_raw_dr_prediction(
            as_raw_prediction(phase4_v4_prediction), experiment.reference
        ),
        phase4_v5_evaluation=evaluate_raw_dr_prediction(
            as_raw_prediction(phase4_v5_prediction), experiment.reference
        ),
        ekf_evaluation=evaluate_hybrid_prediction(ekf_prediction, experiment.reference),
        hybrid_evaluation=evaluate_hybrid_prediction(hybrid_prediction, experiment.reference),
        processing_seconds=seconds,
    )
