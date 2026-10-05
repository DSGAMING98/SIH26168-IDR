"""Evaluation-only comparison of raw DR predictions with hidden reference data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .blackout import EvaluationReference
from .dead_reckoning import PhoneInitialization, RawDRPrediction
from .evaluation import (
    geodetic_to_local_xy_m,
    great_circle_distance_m,
    path_distance_m,
    position_error_series_m,
    summarize_position_errors,
)


UNREALISTIC_SPEED_THRESHOLD_MPS = 70.0


@dataclass(frozen=True)
class RawDREvaluation:
    metrics: dict[str, Any]
    timeseries: pd.DataFrame


def evaluate_raw_dr_prediction(
    prediction: RawDRPrediction,
    reference: EvaluationReference,
    unrealistic_speed_threshold_mps: float = UNREALISTIC_SPEED_THRESHOLD_MPS,
) -> RawDREvaluation:
    """Compare a completed prediction with VBOX only on the evaluation side."""

    if unrealistic_speed_threshold_mps <= 0 or not np.isfinite(
        unrealistic_speed_threshold_mps
    ):
        raise ValueError("Unrealistic-speed threshold must be finite and positive.")
    predicted = prediction.data.reset_index(drop=True)
    reference_data = reference.data
    if predicted.empty:
        raise ValueError("Prediction cannot be empty.")
    if reference_data["runtime_elapsed_s"].duplicated().any():
        raise ValueError("Evaluation reference elapsed timestamps must be unique.")
    indexed_reference = reference_data.set_index("runtime_elapsed_s", drop=False)
    try:
        aligned_reference = indexed_reference.loc[
            predicted["elapsed_s"].to_numpy(dtype=float)
        ].reset_index(drop=True)
    except KeyError as error:
        raise ValueError("Prediction timestamps do not align with the reference.") from error
    if not np.array_equal(
        predicted["elapsed_s"].to_numpy(dtype=float),
        aligned_reference["runtime_elapsed_s"].to_numpy(dtype=float),
    ):
        raise ValueError("Prediction/reference timestamp mismatch.")

    initialization = prediction.initialization
    reference_local = geodetic_to_local_xy_m(
        aligned_reference["latitude_deg"],
        aligned_reference["longitude_deg"],
        initialization.origin_latitude_deg,
        initialization.origin_longitude_deg,
    )
    predicted_xy = predicted[["estimated_x_m", "estimated_y_m"]].to_numpy(dtype=float)
    reference_xy = np.column_stack((reference_local.x_east_m, reference_local.y_north_m))
    predicted_relative = predicted_xy - predicted_xy[0]
    reference_relative = reference_xy - reference_xy[0]
    relative_error = np.linalg.norm(predicted_relative - reference_relative, axis=1)
    absolute_error = position_error_series_m(
        predicted["estimated_latitude_deg"],
        predicted["estimated_longitude_deg"],
        aligned_reference["latitude_deg"],
        aligned_reference["longitude_deg"],
    )
    reference_distance_m = path_distance_m(
        aligned_reference["latitude_deg"], aligned_reference["longitude_deg"]
    )
    relative_metrics = summarize_position_errors(relative_error, reference_distance_m)

    initialization_matches = np.flatnonzero(
        np.isclose(
            reference_data["runtime_elapsed_s"].to_numpy(dtype=float),
            initialization.observation_elapsed_s,
            rtol=0.0,
            atol=1e-9,
        )
    )
    if not initialization_matches.size:
        raise ValueError("Initialization timestamp is absent from the evaluation reference.")
    initial_reference = reference_data.iloc[int(initialization_matches[-1])]
    initial_offset_m = float(
        great_circle_distance_m(
            initialization.origin_latitude_deg,
            initialization.origin_longitude_deg,
            float(initial_reference["latitude_deg"]),
            float(initial_reference["longitude_deg"]),
        )
    )

    predicted_speed = predicted["estimated_speed_mps"].to_numpy(dtype=float)
    horizontal_acceleration = np.linalg.norm(
        predicted[["local_acceleration_x_mps2", "local_acceleration_y_mps2"]].to_numpy(dtype=float),
        axis=1,
    )
    azimuth_unwrapped = np.unwrap(
        np.radians(predicted["orientation_azimuth_deg"].to_numpy(dtype=float))
    )
    unrealistic = predicted_speed > unrealistic_speed_threshold_mps
    metrics: dict[str, Any] = {
        **relative_metrics.to_dict(),
        "absolute_initial_phone_gnss_vbox_offset_m": initial_offset_m,
        "absolute_first_blackout_error_m": float(absolute_error[0]),
        "absolute_final_position_error_m": float(absolute_error[-1]),
        "final_predicted_speed_mps": float(predicted_speed[-1]),
        "minimum_predicted_speed_mps": float(np.min(predicted_speed)),
        "maximum_predicted_speed_mps": float(np.max(predicted_speed)),
        "unrealistic_speed_threshold_mps": float(unrealistic_speed_threshold_mps),
        "unrealistic_speed_sample_count": int(np.count_nonzero(unrealistic)),
        "unrealistic_speed_fraction": float(np.mean(unrealistic)),
        "mean_horizontal_acceleration_mps2": float(np.mean(horizontal_acceleration)),
        "horizontal_acceleration_std_mps2": float(np.std(horizontal_acceleration)),
        "maximum_horizontal_acceleration_mps2": float(np.max(horizontal_acceleration)),
        "absolute_azimuth_variation_deg": float(np.sum(np.abs(np.diff(azimuth_unwrapped))) * 180.0 / np.pi),
        "pitch_std_deg": float(np.std(predicted["orientation_pitch_deg"])),
        "roll_std_deg": float(np.std(predicted["orientation_roll_deg"])),
    }
    timeseries = predicted.copy()
    timeseries["blackout_elapsed_s"] = (
        timeseries["elapsed_s"] - float(timeseries["elapsed_s"].iloc[0])
    )
    timeseries["predicted_relative_x_m"] = predicted_relative[:, 0]
    timeseries["predicted_relative_y_m"] = predicted_relative[:, 1]
    timeseries["reference_relative_x_m"] = reference_relative[:, 0]
    timeseries["reference_relative_y_m"] = reference_relative[:, 1]
    timeseries["relative_position_error_m"] = relative_error
    timeseries["absolute_position_error_m"] = absolute_error
    timeseries["reference_speed_mps"] = (
        aligned_reference["velocity_kmh"].to_numpy(dtype=float) / 3.6
    )
    return RawDREvaluation(metrics=metrics, timeseries=timeseries)
