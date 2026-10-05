"""Frozen zero-shot runtime pipeline for Phase 8.

No target reference, target labels, map, training, or target-derived parameter
selection enters this module.  Dataset-specific work is limited to causal unit,
rate, mounting, and coordinate adaptation into the already frozen estimators.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..calibrated_dr import (
    Phase4Calibration,
    Phase4Settings,
    build_phase4_calibration,
    integrate_calibrated_dead_reckoning,
)
from ..dead_reckoning import RawDRPrediction
from ..evaluation import local_xy_to_geodetic
from ..hybrid.hybrid_idr import HybridPrediction, HybridSettings, run_hybrid_estimator
from ..ml.velocity_model import VelocityModelBundle
from .canonical import RuntimeBlackout


G_STANDARD_MPS2 = 9.80665
VARIANT_IDS: tuple[str, ...] = (
    "C0_RAW_ADAPTED",
    "C1_PHASE4_ADAPTED",
    "C2_FROZEN_PHASE5_EKF",
    "C3_FROZEN_PHASE5_HYBRID",
)


def _wrap_degrees(value: np.ndarray | float) -> np.ndarray | float:
    result = np.asarray(value) % 360.0
    return float(result) if result.ndim == 0 else result


def _causal_gravity(acceleration: np.ndarray, dt: np.ndarray, time_constant_s: float) -> np.ndarray:
    gravity = np.empty_like(acceleration)
    state = acceleration[0].copy()
    for index, delta in enumerate(dt):
        alpha = 1.0 - np.exp(-delta / time_constant_s)
        state = state + alpha * (acceleration[index] - state)
        norm = np.linalg.norm(state)
        if norm < 1e-6:
            raise ValueError("Cannot estimate gravity from a zero accelerometer vector.")
        gravity[index] = state / norm * G_STANDARD_MPS2
    return gravity


def estimate_mounting_forward_axis(
    sensor_history: pd.DataFrame,
    *,
    gravity_time_constant_s: float = 2.0,
    calibration_window_s: float = 60.0,
) -> np.ndarray:
    """Infer a fixed device-horizontal motion axis without labels or future rows."""

    frame = sensor_history.sort_values("elapsed_s").reset_index(drop=True)
    elapsed = frame["elapsed_s"].to_numpy(dtype=float)
    dt = np.diff(elapsed, prepend=elapsed[0] - np.median(np.diff(elapsed)))
    acceleration = frame[[f"accelerometer_{a}_mps2" for a in "xyz"]].to_numpy(dtype=float)
    gravity = _causal_gravity(acceleration, dt, gravity_time_constant_s)
    up = gravity / G_STANDARD_MPS2
    linear = acceleration - gravity
    horizontal = linear - np.sum(linear * up, axis=1)[:, None] * up
    selected = elapsed >= elapsed[-1] - calibration_window_s
    covariance = np.cov(horizontal[selected], rowvar=False)
    values, vectors = np.linalg.eigh(covariance)
    axis = vectors[:, int(np.argmax(values))]
    mean_up = np.mean(up[selected], axis=0)
    mean_up /= np.linalg.norm(mean_up)
    axis = axis - np.dot(axis, mean_up) * mean_up
    if np.linalg.norm(axis) < 0.1:
        candidates = np.eye(3)
        axis = candidates[int(np.argmin(np.abs(candidates @ mean_up)))]
        axis = axis - np.dot(axis, mean_up) * mean_up
    axis /= np.linalg.norm(axis)
    # Eigenvector sign is arbitrary. A deterministic sign keeps repeated runs identical;
    # pre-blackout WLS/course-to-magnetic yaw alignment resolves the 180-degree ambiguity.
    largest = int(np.argmax(np.abs(axis)))
    if axis[largest] < 0:
        axis = -axis
    return axis


def _magnetic_heading_axis(
    gravity: np.ndarray, magnetic: np.ndarray, forward_axis_device: np.ndarray
) -> np.ndarray:
    """Heading of the inferred mounting axis, clockwise from magnetic North."""

    up = gravity / np.linalg.norm(gravity, axis=1)[:, None]
    east = np.cross(magnetic, up)
    east_norm = np.linalg.norm(east, axis=1)
    heading = np.empty(len(gravity), dtype=float)
    previous = 0.0
    device_forward = np.asarray(forward_axis_device, dtype=float)
    if device_forward.shape != (3,) or not np.all(np.isfinite(device_forward)):
        raise ValueError("Forward mounting axis must be one finite three-vector.")
    for index in range(len(gravity)):
        if east_norm[index] < 1e-6:
            heading[index] = previous
            continue
        east_axis = east[index] / east_norm[index]
        north_axis = np.cross(up[index], east_axis)
        forward = device_forward - np.dot(device_forward, up[index]) * up[index]
        norm = np.linalg.norm(forward)
        if norm < 0.1:
            heading[index] = previous
            continue
        forward /= norm
        previous = float(np.degrees(np.arctan2(np.dot(forward, east_axis), np.dot(forward, north_axis))) % 360.0)
        heading[index] = previous
    return heading


def adapt_runtime_sensor_frame(
    sensor_frame: pd.DataFrame,
    *,
    gravity_time_constant_s: float = 2.0,
    forward_axis_device: np.ndarray | None = None,
) -> pd.DataFrame:
    """Causally adapt arbitrary Android device axes to pseudo vehicle axes.

    The adapter projects a strictly pre-blackout, runtime-only mounting axis
    into the gravity-horizontal plane as vehicle forward, derives left as
    ``up x forward``, and writes a level pseudo frame (+X forward, +Y left,
    +Z up) expected by the frozen S1 estimator. This is a declared portability
    assumption, not target-label calibration.
    """

    if sensor_frame.empty:
        raise ValueError("Sensor frame cannot be empty.")
    frame = sensor_frame.sort_values("elapsed_s").reset_index(drop=True)
    elapsed = frame["elapsed_s"].to_numpy(dtype=float)
    dt = np.diff(elapsed, prepend=elapsed[0] - np.median(np.diff(elapsed)))
    if np.any(dt <= 0) or not np.isfinite(gravity_time_constant_s) or gravity_time_constant_s <= 0:
        raise ValueError("Adaptation requires increasing timestamps and positive gravity time constant.")
    acceleration = frame[[f"accelerometer_{a}_mps2" for a in "xyz"]].to_numpy(dtype=float)
    gyroscope = frame[[f"gyroscope_{a}_radps" for a in "xyz"]].to_numpy(dtype=float)
    magnetic = frame[[f"magnetic_field_{a}_ut" for a in "xyz"]].to_numpy(dtype=float)
    if not np.all(np.isfinite(np.column_stack((acceleration, gyroscope, magnetic)))):
        raise ValueError("Adaptation sensor values must be finite.")

    gravity = _causal_gravity(acceleration, dt, gravity_time_constant_s)
    up = gravity / G_STANDARD_MPS2
    axis = np.array([1.0, 0.0, 0.0]) if forward_axis_device is None else np.asarray(forward_axis_device, dtype=float)
    forward = axis - np.sum(axis * up, axis=1)[:, None] * up
    norm = np.linalg.norm(forward, axis=1)
    if np.any(norm < 0.1):
        raise ValueError("Inferred mounting axis is too close to vertical for vehicle adaptation.")
    forward /= norm[:, None]
    left = np.cross(up, forward)
    left /= np.linalg.norm(left, axis=1)[:, None]
    linear = acceleration - gravity
    linear_vehicle = np.column_stack(
        (np.sum(linear * forward, axis=1), np.sum(linear * left, axis=1), np.sum(linear * up, axis=1))
    )

    vertical_gyro = np.sum(gyroscope * up, axis=1)
    horizontal_gyro = np.sqrt(np.maximum(0.0, np.sum(np.square(gyroscope), axis=1) - np.square(vertical_gyro)))
    magnetic_norm = np.linalg.norm(magnetic, axis=1)
    azimuth = _magnetic_heading_axis(gravity, magnetic, axis)
    timestamp = pd.to_datetime(frame["timestamp_utc_ms"].to_numpy(dtype=np.int64), unit="ms", utc=True)
    return pd.DataFrame(
        {
            "elapsed_s": elapsed,
            "time_since_start_ms": elapsed * 1000.0,
            "timestamp_local": timestamp,
            "accelerometer_x_mps2": linear_vehicle[:, 0],
            "accelerometer_y_mps2": linear_vehicle[:, 1],
            "accelerometer_z_mps2": linear_vehicle[:, 2] + G_STANDARD_MPS2,
            "gravity_x_mps2": np.zeros(len(frame)),
            "gravity_y_mps2": np.zeros(len(frame)),
            "gravity_z_mps2": np.full(len(frame), G_STANDARD_MPS2),
            "gyroscope_x_radps": horizontal_gyro,
            # Frozen S1 convention is course_rate = -gyro_y. Android course
            # rate is -omega dot Up, hence pseudo gyro_y = omega dot Up.
            "gyroscope_y_radps": vertical_gyro,
            "gyroscope_z_radps": np.zeros(len(frame)),
            "magnetic_field_x_ut": magnetic_norm,
            "magnetic_field_y_ut": np.zeros(len(frame)),
            "magnetic_field_z_ut": np.zeros(len(frame)),
            "orientation_azimuth_deg": azimuth,
            "orientation_pitch_deg": np.zeros(len(frame)),
            "orientation_roll_deg": np.zeros(len(frame)),
        }
    )


def _aligned_gnss(sensor: pd.DataFrame, gnss: pd.DataFrame) -> pd.DataFrame:
    left = sensor[["elapsed_s"]].copy().sort_values("elapsed_s")
    right = gnss.sort_values("elapsed_s").copy()
    aligned = pd.merge_asof(left, right, on="elapsed_s", direction="backward")
    aligned = aligned.dropna().reset_index(drop=True)
    aligned["timestamp_local"] = pd.to_datetime(
        np.rint(aligned["timestamp_utc_ms"]).astype(np.int64), unit="ms", utc=True
    )
    return aligned


@dataclass(frozen=True)
class PreparedRuntime:
    sensor_history: pd.DataFrame
    gnss_history: pd.DataFrame
    blackout_sensor_data: pd.DataFrame
    calibration: Phase4Calibration
    assumptions: dict[str, Any]


def prepare_runtime(
    blackout: RuntimeBlackout,
    phase4_settings: Phase4Settings,
    *,
    gravity_time_constant_s: float = 2.0,
) -> PreparedRuntime:
    """Finish runtime-only adaptation and frozen pre-blackout calibration."""

    combined = pd.concat(
        [blackout.sensor_history, blackout.blackout_sensor_data], ignore_index=True
    ).sort_values("elapsed_s").reset_index(drop=True)
    mounting_axis = estimate_mounting_forward_axis(
        blackout.sensor_history,
        gravity_time_constant_s=gravity_time_constant_s,
        calibration_window_s=phase4_settings.calibration_window_s,
    )
    adapted = adapt_runtime_sensor_frame(
        combined,
        gravity_time_constant_s=gravity_time_constant_s,
        forward_axis_device=mounting_axis,
    )
    sensor_history = adapted.loc[adapted["elapsed_s"] < blackout.start_s].copy()
    active = (adapted["elapsed_s"] >= blackout.start_s) & (adapted["elapsed_s"] < blackout.end_s)
    blackout_sensor = adapted.loc[active].copy().reset_index(drop=True)
    blackout_sensor["gnss_available"] = False
    gnss_history = _aligned_gnss(sensor_history, blackout.gnss_history)
    # build_phase4_calibration requires solution changes at exact sensor times;
    # merge_asof makes each runtime WLS solution causal and sample-aligned.
    calibration = build_phase4_calibration(sensor_history, gnss_history, blackout.start_s, phase4_settings)
    return PreparedRuntime(
        sensor_history,
        gnss_history,
        blackout_sensor,
        calibration,
        {
            "device_mounting": "principal horizontal acceleration axis from the strictly pre-blackout 60-second runtime IMU window",
            "device_forward_axis": [float(value) for value in mounting_axis],
            "gravity": f"causal first-order low-pass, tau={gravity_time_constant_s:g}s, normalized to {G_STANDARD_MPS2}m/s^2",
            "yaw": "pre-blackout runtime WLS course minus magnetic device +Y heading through frozen Phase 4 calibration",
            "pseudo_frame": "+X forward, +Y left, +Z up",
        },
    )


def _run_raw(prepared: PreparedRuntime) -> RawDRPrediction:
    frame = prepared.blackout_sensor_data.reset_index(drop=True)
    calibration = prepared.calibration
    elapsed = frame["elapsed_s"].to_numpy(dtype=float)
    dt = np.diff(elapsed, prepend=calibration.last_sensor_elapsed_s)
    forward = frame["accelerometer_x_mps2"].to_numpy(dtype=float)
    left = frame["accelerometer_y_mps2"].to_numpy(dtype=float)
    heading = _wrap_degrees(
        frame["orientation_azimuth_deg"].to_numpy(dtype=float) + calibration.mounting_yaw_offset_deg
    )
    initial_heading = np.radians(calibration.initialization.initial_heading_deg)
    velocity = np.array(
        [calibration.initialization.initial_speed_mps * np.sin(initial_heading), calibration.initialization.initial_speed_mps * np.cos(initial_heading)],
        dtype=float,
    )
    position = np.zeros(2, dtype=float)
    positions = np.empty((len(frame), 2), dtype=float)
    velocities = np.empty((len(frame), 2), dtype=float)
    accelerations = np.empty((len(frame), 2), dtype=float)
    previous = np.zeros(2, dtype=float)
    for index, delta in enumerate(dt):
        angle = np.radians(float(heading[index]))
        forward_nav = np.array([np.sin(angle), np.cos(angle)])
        left_nav = np.array([-np.cos(angle), np.sin(angle)])
        current = forward[index] * forward_nav + left[index] * left_nav
        next_velocity = velocity + 0.5 * (previous + current) * delta
        position += 0.5 * (velocity + next_velocity) * delta
        velocity = next_velocity
        previous = current
        positions[index], velocities[index], accelerations[index] = position, velocity, current
    latitude, longitude = local_xy_to_geodetic(
        positions[:, 0], positions[:, 1], calibration.initialization.origin_latitude_deg, calibration.initialization.origin_longitude_deg
    )
    data = pd.DataFrame(
        {
            "elapsed_s": elapsed,
            "dt_s": dt,
            "estimated_x_m": positions[:, 0],
            "estimated_y_m": positions[:, 1],
            "estimated_velocity_x_mps": velocities[:, 0],
            "estimated_velocity_y_mps": velocities[:, 1],
            "estimated_speed_mps": np.linalg.norm(velocities, axis=1),
            "local_acceleration_x_mps2": accelerations[:, 0],
            "local_acceleration_y_mps2": accelerations[:, 1],
            "local_acceleration_z_mps2": frame["accelerometer_z_mps2"].to_numpy(dtype=float) - G_STANDARD_MPS2,
            "orientation_azimuth_deg": heading,
            "orientation_pitch_deg": np.zeros(len(frame)),
            "orientation_roll_deg": np.zeros(len(frame)),
            "estimated_latitude_deg": latitude,
            "estimated_longitude_deg": longitude,
        }
    )
    return RawDRPrediction(data, calibration.initialization, algorithm="phase8_raw_adapted_v1")


@dataclass(frozen=True)
class ScenarioPredictions:
    prepared: PreparedRuntime
    predictions: dict[str, RawDRPrediction | HybridPrediction | Any]
    processing_seconds: dict[str, float]


def run_frozen_variants(
    prepared: PreparedRuntime,
    phase4_settings: Phase4Settings,
    hybrid_settings: HybridSettings,
    model_bundle: VelocityModelBundle,
) -> ScenarioPredictions:
    """Run all declared variants with frozen source-domain settings/checkpoint."""

    predictions: dict[str, Any] = {}
    seconds: dict[str, float] = {}
    operations = (
        ("C0_RAW_ADAPTED", lambda: _run_raw(prepared)),
        (
            "C1_PHASE4_ADAPTED",
            lambda: integrate_calibrated_dead_reckoning(
                prepared.blackout_sensor_data, prepared.calibration, phase4_settings, "V5_PHASE4_COMBINED"
            ),
        ),
        (
            "C2_FROZEN_PHASE5_EKF",
            lambda: run_hybrid_estimator(
                prepared.blackout_sensor_data, prepared.calibration, phase4_settings, hybrid_settings, None, None
            ),
        ),
        (
            "C3_FROZEN_PHASE5_HYBRID",
            lambda: run_hybrid_estimator(
                prepared.blackout_sensor_data, prepared.calibration, phase4_settings, hybrid_settings, model_bundle, None
            ),
        ),
    )
    for variant, operation in operations:
        started = time.perf_counter()
        predictions[variant] = operation()
        seconds[variant] = time.perf_counter() - started
    return ScenarioPredictions(prepared, predictions, seconds)


def load_frozen_settings(root: Path) -> tuple[Phase4Settings, HybridSettings]:
    import json

    phase4 = json.loads((root / "configs/phase4/io_vnbd_s1_classical.json").read_text(encoding="utf-8"))
    hybrid = json.loads((root / "configs/phase5/io_vnbd_s1_ekf.json").read_text(encoding="utf-8"))
    return Phase4Settings.from_dict(phase4), HybridSettings.from_dict(hybrid)
