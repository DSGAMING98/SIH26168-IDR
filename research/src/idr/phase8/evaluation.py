"""Offline-only Phase 8 cross-dataset evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from ..blackout import EvaluationReference
from ..calibrated_dr import CalibratedDRPrediction, as_raw_prediction
from ..dead_reckoning import RawDRPrediction
from ..hybrid.hybrid_idr import HybridPrediction
from ..ml.features import FEATURE_ORDER
from ..ml.velocity_model import VelocityModelBundle
from ..raw_dr_evaluation import evaluate_raw_dr_prediction
from .canonical import CanonicalEvaluationReference


@dataclass(frozen=True)
class CrossDatasetEvaluation:
    metrics: dict[str, Any]
    timeseries: pd.DataFrame


def _interpolated_reference(reference: CanonicalEvaluationReference, elapsed: np.ndarray) -> EvaluationReference:
    source = reference.data
    x = source["elapsed_s"].to_numpy(dtype=float)
    if elapsed.min() < x.min() or elapsed.max() > x.max():
        raise ValueError("Prediction lies outside the evaluation reference.")
    latitude = np.interp(elapsed, x, source["latitude_deg"].to_numpy(dtype=float))
    longitude_unwrapped = np.unwrap(np.radians(source["longitude_deg"].to_numpy(dtype=float)))
    longitude = np.degrees(np.interp(elapsed, x, longitude_unwrapped))
    speed = np.interp(elapsed, x, source["speed_mps"].to_numpy(dtype=float))
    return EvaluationReference(
        pd.DataFrame(
            {
                "runtime_elapsed_s": elapsed,
                "latitude_deg": latitude,
                "longitude_deg": longitude,
                "velocity_kmh": speed * 3.6,
            }
        )
    )


def _raw_prediction(prediction: Any) -> RawDRPrediction:
    if isinstance(prediction, RawDRPrediction):
        return prediction
    if isinstance(prediction, CalibratedDRPrediction):
        return as_raw_prediction(prediction)
    if isinstance(prediction, HybridPrediction):
        return RawDRPrediction(
            prediction.data,
            prediction.calibration.initialization,
            algorithm=prediction.algorithm,
            integration_method="frozen Phase 5 six-state EKF",
            coordinate_frame=prediction.coordinate_frame,
        )
    raise TypeError(f"Unsupported prediction type: {type(prediction)!r}")


def evaluate_completed_prediction(
    prediction: Any,
    reference: CanonicalEvaluationReference,
) -> CrossDatasetEvaluation:
    """Attach hidden reference only after a runtime prediction is complete."""

    raw = _raw_prediction(prediction)
    prediction_times = raw.data["elapsed_s"].to_numpy(dtype=float)
    all_times = np.unique(np.append(prediction_times, raw.initialization.observation_elapsed_s))
    evaluation_reference = _interpolated_reference(reference, all_times)
    base = evaluate_raw_dr_prediction(raw, evaluation_reference)
    reference_frame = reference.data
    ref_elapsed = reference_frame["elapsed_s"].to_numpy(dtype=float)
    ref_speed = np.interp(prediction_times, ref_elapsed, reference_frame["speed_mps"].to_numpy(dtype=float))
    predicted_speed = raw.data["estimated_speed_mps"].to_numpy(dtype=float)
    speed_error = predicted_speed - ref_speed
    if "estimated_yaw_deg" in raw.data:
        predicted_heading = raw.data["estimated_yaw_deg"].to_numpy(dtype=float)
    elif "stabilized_heading_deg" in raw.data:
        predicted_heading = raw.data["stabilized_heading_deg"].to_numpy(dtype=float)
    else:
        predicted_heading = raw.data["orientation_azimuth_deg"].to_numpy(dtype=float)
    bearing_unwrapped = np.unwrap(np.radians(reference_frame["bearing_deg"].to_numpy(dtype=float)))
    reference_heading = np.degrees(np.interp(prediction_times, ref_elapsed, bearing_unwrapped)) % 360.0
    heading_error = (predicted_heading - reference_heading + 180.0) % 360.0 - 180.0
    metrics = {
        **base.metrics,
        "speed_mae_mps": float(np.mean(np.abs(speed_error))),
        "speed_rmse_mps": float(np.sqrt(np.mean(np.square(speed_error)))),
        "heading_mae_deg": float(np.mean(np.abs(heading_error))),
        "heading_rmse_deg": float(np.sqrt(np.mean(np.square(heading_error)))),
        "heading_p95_absolute_error_deg": float(np.percentile(np.abs(heading_error), 95)),
        "map_matching_applicable": False,
        "phase7_reacquisition_applicable": False,
    }
    timeseries = base.timeseries.copy()
    timeseries["reference_speed_mps"] = ref_speed
    timeseries["speed_error_mps"] = speed_error
    timeseries["reference_heading_deg"] = reference_heading
    timeseries["heading_error_deg"] = heading_error
    return CrossDatasetEvaluation(metrics, timeseries)


def hybrid_feature_shift(
    prediction: HybridPrediction,
    model_bundle: VelocityModelBundle,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Compare target runtime features with the frozen S1 training scaler."""

    features = prediction.feature_data.loc[:, list(FEATURE_ORDER)].to_numpy(dtype=float)
    normalized = model_bundle.scaler.transform(features)
    lower = np.asarray(model_bundle.scaler.normalized_lower_bounds, dtype=float)
    upper = np.asarray(model_bundle.scaler.normalized_upper_bounds, dtype=float)
    exceedance = np.maximum(np.maximum(lower - normalized, normalized - upper), 0.0)
    rows = pd.DataFrame(
        {
            "feature": FEATURE_ORDER,
            "target_mean": np.mean(features, axis=0),
            "target_std": np.std(features, axis=0),
            "normalized_mean": np.mean(normalized, axis=0),
            "normalized_std": np.std(normalized, axis=0),
            # Ignore sub-micro normalized floating-point edge effects when
            # reporting distribution shift. Runtime OOD gating itself remains
            # byte-for-byte unchanged and uses its frozen exact computation.
            "fraction_outside_training_bounds": np.mean(exceedance > 1e-6, axis=0),
            "maximum_exceedance": np.max(exceedance, axis=0),
        }
    )
    row_max = np.max(exceedance, axis=1)
    return rows, {
        "mean_max_exceedance": float(np.mean(row_max)),
        "maximum_exceedance": float(np.max(row_max)),
        "fraction_above_soft_threshold": float(np.mean(row_max > 0.5)),
        "fraction_above_hard_threshold": float(np.mean(row_max > 3.0)),
    }
