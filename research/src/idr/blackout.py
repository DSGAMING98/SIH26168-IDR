"""Deterministic, leakage-resistant GNSS blackout experiments."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from .evaluation import path_distance_m
from .io_vnbd import IOVNBDJourney


# GPS orientation/course is distinct from Android sensor orientation in the
# IO-VNBD schema. Every source and derived phone-GNSS value is kept out of the
# aligned runtime sensor frame.
GNSS_DERIVED_FIELDS: tuple[str, ...] = (
    "gps_latitude_deg",
    "gps_longitude_deg",
    "gps_altitude_m",
    "gps_speed_source",
    "gps_speed_mps",
    "gps_speed_kmh",
    "gps_accuracy_m",
    "gps_orientation_deg",
    "gps_satellites_in_range",
)

RUNTIME_SENSOR_FIELDS: tuple[str, ...] = (
    "elapsed_s",
    "time_since_start_ms",
    "timestamp_local",
    "accelerometer_x_mps2",
    "accelerometer_y_mps2",
    "accelerometer_z_mps2",
    "gravity_x_mps2",
    "gravity_y_mps2",
    "gravity_z_mps2",
    "gyroscope_x_radps",
    "gyroscope_y_radps",
    "gyroscope_z_radps",
    "magnetic_field_x_ut",
    "magnetic_field_y_ut",
    "magnetic_field_z_ut",
    "orientation_azimuth_deg",
    "orientation_pitch_deg",
    "orientation_roll_deg",
)

IMU_FIELDS: tuple[str, ...] = (
    "accelerometer_x_mps2",
    "accelerometer_y_mps2",
    "accelerometer_z_mps2",
    "gravity_x_mps2",
    "gravity_y_mps2",
    "gravity_z_mps2",
    "gyroscope_x_radps",
    "gyroscope_y_radps",
    "gyroscope_z_radps",
    "magnetic_field_x_ut",
    "magnetic_field_y_ut",
    "magnetic_field_z_ut",
)


@dataclass(frozen=True)
class BlackoutWindow:
    """Requested half-open blackout interval: start_s <= t < start_s+duration_s."""

    start_s: float
    duration_s: float

    @property
    def end_s(self) -> float:
        return self.start_s + self.duration_s


@dataclass(frozen=True)
class BlackoutMetadata:
    session_id: str
    requested_start_s: float
    requested_duration_s: float
    requested_end_s_exclusive: float
    interval_semantics: str
    masked_sample_count: int
    actual_first_masked_sample_s: float
    actual_last_masked_sample_s: float
    actual_end_exclusive_sample_s: float
    actual_first_masked_timestamp_local: str
    actual_last_masked_timestamp_local: str
    actual_end_exclusive_timestamp_local: str
    actual_masked_duration_s: float
    sampling_tolerance_s: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RuntimeDataset:
    """Only data that a future estimator may receive.

    ``sensor_data`` is aligned at the phone sampling rate and contains no GNSS
    measurements. ``gnss_observations`` contains GNSS rows only where
    ``gnss_available`` is true; blackout rows are absent rather than filled with
    sensitive values.
    """

    sensor_data: pd.DataFrame
    gnss_observations: pd.DataFrame


@dataclass(frozen=True)
class EvaluationReference:
    """Hidden VBOX reference; pass this only to evaluation/visualization code."""

    data: pd.DataFrame


@dataclass(frozen=True)
class ExperimentDataset:
    runtime: RuntimeDataset
    reference: EvaluationReference
    metadata: BlackoutMetadata


def _validate_window(elapsed_s: np.ndarray, window: BlackoutWindow) -> float:
    if not np.isfinite(window.start_s):
        raise ValueError("Blackout start must be finite.")
    if not np.isfinite(window.duration_s):
        raise ValueError("Blackout duration must be finite.")
    if window.duration_s <= 0:
        raise ValueError("Blackout duration must be greater than zero.")
    if elapsed_s.ndim != 1 or elapsed_s.size < 2 or not np.all(np.isfinite(elapsed_s)):
        raise ValueError("Journey elapsed time must contain finite ordered samples.")
    delta = np.diff(elapsed_s)
    if np.any(delta <= 0):
        raise ValueError("Journey elapsed time must be strictly increasing.")
    sampling_tolerance = float(np.median(delta))
    if window.start_s < float(elapsed_s[0]):
        raise ValueError("Blackout start is before the session.")
    if window.end_s > float(elapsed_s[-1]):
        raise ValueError("Blackout end is after the session.")
    return sampling_tolerance


def create_blackout_experiment(
    journey: IOVNBDJourney,
    window: BlackoutWindow,
) -> ExperimentDataset:
    """Create isolated runtime/reference domains for one deterministic blackout."""

    if len(journey.smartphone) != len(journey.vehicle):
        raise ValueError("Synchronized smartphone and VBOX streams must have equal rows.")
    phone = journey.smartphone.reset_index(drop=True)
    vehicle = journey.vehicle.reset_index(drop=True)
    elapsed = phone["elapsed_s"].to_numpy(dtype=float)
    tolerance = _validate_window(elapsed, window)
    blackout = (elapsed >= window.start_s) & (elapsed < window.end_s)
    indices = np.flatnonzero(blackout)
    if indices.size == 0:
        raise ValueError("Requested blackout contains no samples.")

    first_index = int(indices[0])
    last_index = int(indices[-1])
    end_exclusive_sample = (
        float(elapsed[last_index + 1])
        if last_index + 1 < elapsed.size
        else float(elapsed[last_index] + tolerance)
    )

    sensor_data = phone.loc[:, list(RUNTIME_SENSOR_FIELDS)].copy()
    sensor_data["gnss_available"] = ~blackout
    gnss_columns = ("elapsed_s", *GNSS_DERIVED_FIELDS)
    gnss_observations = phone.loc[~blackout, list(gnss_columns)].copy().reset_index(drop=True)

    reference_data = vehicle.copy()
    reference_data.insert(0, "runtime_elapsed_s", elapsed)
    reference_data["is_blackout"] = blackout

    metadata = BlackoutMetadata(
        session_id=journey.session_id,
        requested_start_s=float(window.start_s),
        requested_duration_s=float(window.duration_s),
        requested_end_s_exclusive=float(window.end_s),
        interval_semantics="half-open [start_s, start_s + duration_s)",
        masked_sample_count=int(indices.size),
        actual_first_masked_sample_s=float(elapsed[first_index]),
        actual_last_masked_sample_s=float(elapsed[last_index]),
        actual_end_exclusive_sample_s=end_exclusive_sample,
        actual_first_masked_timestamp_local=phone["timestamp_local"].iloc[first_index].isoformat(),
        actual_last_masked_timestamp_local=phone["timestamp_local"].iloc[last_index].isoformat(),
        actual_end_exclusive_timestamp_local=phone["timestamp_local"].iloc[last_index + 1].isoformat(),
        actual_masked_duration_s=float(end_exclusive_sample - elapsed[first_index]),
        sampling_tolerance_s=tolerance,
    )
    return ExperimentDataset(
        runtime=RuntimeDataset(sensor_data=sensor_data, gnss_observations=gnss_observations),
        reference=EvaluationReference(data=reference_data),
        metadata=metadata,
    )


def reference_blackout_segment(experiment: ExperimentDataset) -> pd.DataFrame:
    """Return the hidden reference segment for evaluation code only."""

    reference = experiment.reference.data
    return reference.loc[reference["is_blackout"]].copy()


def reference_blackout_distance_m(experiment: ExperimentDataset) -> float:
    """Calculate VBOX reference path distance inside the masked sample interval."""

    segment = reference_blackout_segment(experiment)
    return path_distance_m(segment["latitude_deg"], segment["longitude_deg"])


def scenario_characteristics(experiment: ExperimentDataset) -> dict[str, float]:
    """Summarize motion from the hidden reference for scenario labeling only."""

    segment = reference_blackout_segment(experiment)
    speed = segment["velocity_kmh"].to_numpy(dtype=float)
    time_s = segment["runtime_elapsed_s"].to_numpy(dtype=float)
    yaw_rate = np.abs(segment["yaw_rate_degps"].to_numpy(dtype=float))
    longitudinal_accel = np.abs(segment["longitudinal_acceleration_g"].to_numpy(dtype=float))
    if len(time_s) > 1:
        dt = np.diff(time_s, prepend=time_s[0])
        dt[0] = float(np.median(np.diff(time_s)))
    else:
        dt = np.zeros_like(time_s)
    return {
        "reference_distance_m": reference_blackout_distance_m(experiment),
        "mean_speed_kmh": float(np.mean(speed)),
        "speed_std_kmh": float(np.std(speed)),
        "minimum_speed_kmh": float(np.min(speed)),
        "maximum_speed_kmh": float(np.max(speed)),
        "stopped_fraction_below_3_kmh": float(np.mean(speed < 3.0)),
        "absolute_yaw_rotation_deg": float(np.sum(yaw_rate * dt)),
        "mean_absolute_longitudinal_acceleration_g": float(np.mean(longitudinal_accel)),
    }


def validate_experiment(
    journey: IOVNBDJourney,
    experiment: ExperimentDataset,
) -> dict[str, bool | float | int]:
    """Run structural checks that guard timing, IMU retention, and GNSS leakage."""

    runtime = experiment.runtime.sensor_data
    observations = experiment.runtime.gnss_observations
    reference = experiment.reference.data
    metadata = experiment.metadata
    inside = ~runtime["gnss_available"].to_numpy(dtype=bool)
    elapsed = runtime["elapsed_s"].to_numpy(dtype=float)
    expected_inside = (
        (elapsed >= metadata.requested_start_s)
        & (elapsed < metadata.requested_end_s_exclusive)
    )
    forbidden_in_runtime = set(GNSS_DERIVED_FIELDS).intersection(runtime.columns)
    observation_inside = (
        (observations["elapsed_s"] >= metadata.requested_start_s)
        & (observations["elapsed_s"] < metadata.requested_end_s_exclusive)
    )
    duration_error = abs(metadata.actual_masked_duration_s - metadata.requested_duration_s)
    checks: dict[str, bool | float | int] = {
        "requested_samples_unavailable": bool(
            np.all(~runtime.loc[expected_inside, "gnss_available"])
        ),
        "outside_samples_available": bool(
            np.all(runtime.loc[~expected_inside, "gnss_available"])
        ),
        "mask_matches_requested_interval": bool(np.array_equal(inside, expected_inside)),
        "forbidden_gnss_fields_absent_from_sensor_data": not forbidden_in_runtime,
        "no_gnss_observations_inside_blackout": not bool(observation_inside.any()),
        "imu_fields_present": set(IMU_FIELDS).issubset(runtime.columns),
        "imu_values_preserved": bool(
            np.allclose(
                runtime.loc[:, list(IMU_FIELDS)].to_numpy(dtype=float),
                journey.smartphone.loc[:, list(IMU_FIELDS)].to_numpy(dtype=float),
                equal_nan=True,
            )
        ),
        "reference_rows_preserved": len(reference) == len(journey.vehicle),
        "runtime_rows_preserved": len(runtime) == len(journey.smartphone),
        "runtime_reference_row_alignment": bool(
            np.array_equal(elapsed, reference["runtime_elapsed_s"].to_numpy(dtype=float))
        ),
        "masked_sample_count_matches": int(np.count_nonzero(inside)) == metadata.masked_sample_count,
        "duration_within_sampling_tolerance": duration_error <= metadata.sampling_tolerance_s + 1e-9,
        "duration_error_s": float(duration_error),
    }
    failed = [name for name, value in checks.items() if isinstance(value, bool) and not value]
    if failed:
        raise AssertionError(f"Blackout validation failed: {failed}")
    return checks
