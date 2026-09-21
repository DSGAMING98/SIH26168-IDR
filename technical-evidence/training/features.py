"""Strictly causal, runtime-only features and blocked-window validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd

from ..blackout import GNSS_DERIVED_FIELDS
from ..calibrated_dr import REFERENCE_ONLY_FIELDS


FEATURE_ORDER: tuple[str, ...] = (
    "conditioned_forward_acceleration_mps2",
    "conditioned_left_acceleration_mps2",
    "gyro_course_rate_radps",
    "gyro_magnitude_radps",
    "gravity_magnitude_mps2",
    "magnetic_magnitude_ut",
    "motion_accel_rms_mps2",
    "motion_gyro_rms_radps",
    "is_likely_stationary",
    "classical_speed_mps",
)


@dataclass(frozen=True)
class CausalWindowBatch:
    inputs: np.ndarray
    targets: np.ndarray | None
    end_indices: np.ndarray


def build_runtime_feature_frame(
    sensor_frame: pd.DataFrame,
    conditioned_frame: pd.DataFrame,
    classical_speed_mps: np.ndarray | pd.Series,
) -> pd.DataFrame:
    """Build the fixed ML feature order without copying other input fields."""

    leaked = (set(GNSS_DERIVED_FIELDS) | set(REFERENCE_ONLY_FIELDS)).intersection(
        sensor_frame.columns
    )
    if leaked:
        raise ValueError(f"Runtime feature input contains forbidden fields: {sorted(leaked)}")
    if len(sensor_frame) != len(conditioned_frame):
        raise ValueError("Sensor and conditioned feature rows must align.")
    required_conditioned = {
        "elapsed_s",
        "conditioned_forward_acceleration_mps2",
        "conditioned_left_acceleration_mps2",
        "gyro_course_rate_radps",
        "magnetic_magnitude_ut",
        "motion_accel_rms_mps2",
        "motion_gyro_rms_radps",
        "motion_state",
    }
    required_sensor = {
        "elapsed_s",
        *(f"gyroscope_{axis}_radps" for axis in "xyz"),
        *(f"gravity_{axis}_mps2" for axis in "xyz"),
    }
    missing = required_conditioned.difference(conditioned_frame.columns) | required_sensor.difference(
        sensor_frame.columns
    )
    if missing:
        raise ValueError(f"Runtime feature inputs are missing: {sorted(missing)}")
    sensor_time = sensor_frame["elapsed_s"].to_numpy(dtype=float)
    conditioned_time = conditioned_frame["elapsed_s"].to_numpy(dtype=float)
    if not np.array_equal(sensor_time, conditioned_time):
        raise ValueError("Sensor and conditioned timestamps are not aligned.")
    speed = np.asarray(classical_speed_mps, dtype=float)
    if speed.shape != (len(sensor_frame),):
        raise ValueError("Classical speed must have one value per runtime sample.")
    gyro = sensor_frame[[f"gyroscope_{axis}_radps" for axis in "xyz"]].to_numpy(dtype=float)
    gravity = sensor_frame[[f"gravity_{axis}_mps2" for axis in "xyz"]].to_numpy(dtype=float)
    result = pd.DataFrame(
        {
            "conditioned_forward_acceleration_mps2": conditioned_frame[
                "conditioned_forward_acceleration_mps2"
            ].to_numpy(dtype=float),
            "conditioned_left_acceleration_mps2": conditioned_frame[
                "conditioned_left_acceleration_mps2"
            ].to_numpy(dtype=float),
            "gyro_course_rate_radps": conditioned_frame["gyro_course_rate_radps"].to_numpy(dtype=float),
            "gyro_magnitude_radps": np.linalg.norm(gyro, axis=1),
            "gravity_magnitude_mps2": np.linalg.norm(gravity, axis=1),
            "magnetic_magnitude_ut": conditioned_frame["magnetic_magnitude_ut"].to_numpy(dtype=float),
            "motion_accel_rms_mps2": conditioned_frame["motion_accel_rms_mps2"].to_numpy(dtype=float),
            "motion_gyro_rms_radps": conditioned_frame["motion_gyro_rms_radps"].to_numpy(dtype=float),
            "is_likely_stationary": (
                conditioned_frame["motion_state"].astype(str).to_numpy() == "LIKELY_STATIONARY"
            ).astype(float),
            "classical_speed_mps": speed,
        },
        columns=list(FEATURE_ORDER),
    )
    if not np.all(np.isfinite(result.to_numpy(dtype=float))):
        raise ValueError("Runtime ML features contain NaN or infinity.")
    return result


def make_causal_windows(
    features: pd.DataFrame | np.ndarray,
    targets: np.ndarray | pd.Series | None,
    *,
    window_steps: int,
    stride_steps: int = 1,
) -> CausalWindowBatch:
    """Create history-only windows whose last row is the prediction time."""

    if window_steps <= 0 or stride_steps <= 0:
        raise ValueError("Window and stride sizes must be positive.")
    values = (
        features.loc[:, list(FEATURE_ORDER)].to_numpy(dtype=np.float32)
        if isinstance(features, pd.DataFrame)
        else np.asarray(features, dtype=np.float32)
    )
    if values.ndim != 2 or not np.all(np.isfinite(values)):
        raise ValueError("Feature matrix must be finite and two-dimensional.")
    target_values = None if targets is None else np.asarray(targets, dtype=np.float32)
    if target_values is not None and target_values.shape != (len(values),):
        raise ValueError("Targets must align one-to-one with feature rows.")
    ends = np.arange(window_steps - 1, len(values), stride_steps, dtype=int)
    windows = np.empty((len(ends), window_steps, values.shape[1]), dtype=np.float32)
    for output_index, end_index in enumerate(ends):
        windows[output_index] = values[end_index - window_steps + 1 : end_index + 1]
    window_targets = None if target_values is None else target_values[ends]
    return CausalWindowBatch(windows, window_targets, ends)


def _intervals_overlap(first: dict[str, Any], second: dict[str, Any]) -> bool:
    return max(float(first["start_s"]), float(second["start_s"])) < min(
        float(first["end_s"]), float(second["end_s"])
    )


def verify_split_manifest(manifest: dict[str, Any]) -> dict[str, bool | int]:
    """Reject benchmark overlap, train/validation overlap, or invalid blocks."""

    train = list(manifest["training_intervals"])
    validation = list(manifest["validation_intervals"])
    quarantine = list(manifest["quarantine_intervals"])
    all_blocks = train + validation + quarantine
    finite_positive = all(
        np.isfinite(float(block["start_s"]))
        and np.isfinite(float(block["end_s"]))
        and float(block["end_s"]) > float(block["start_s"])
        for block in all_blocks
    )
    if not finite_positive:
        raise ValueError("Every split interval must be finite and positive length.")
    train_validation_overlap = any(_intervals_overlap(a, b) for a in train for b in validation)
    development_quarantine_overlap = any(
        _intervals_overlap(a, b) for a in train + validation for b in quarantine
    )
    within_split_overlap = any(
        _intervals_overlap(blocks[i], blocks[j])
        for blocks in (train, validation)
        for i in range(len(blocks))
        for j in range(i + 1, len(blocks))
    )
    if train_validation_overlap or development_quarantine_overlap or within_split_overlap:
        raise ValueError("Blocked split contains overlapping train/validation/quarantine intervals.")
    return {
        "finite_positive_intervals": finite_positive,
        "train_validation_disjoint": not train_validation_overlap,
        "benchmark_quarantine_disjoint": not development_quarantine_overlap,
        "within_split_disjoint": not within_split_overlap,
        "training_interval_count": len(train),
        "validation_interval_count": len(validation),
        "quarantine_interval_count": len(quarantine),
    }
