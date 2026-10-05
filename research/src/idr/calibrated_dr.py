"""Calibrated, causal, reference-free classical dead reckoning for Phase 4."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

import numpy as np
import pandas as pd

from .attitude import (
    circular_mean_deg,
    gravity_euler_diagnostics,
    gravity_vehicle_basis,
    signed_angle_difference_deg,
    wrap_degrees,
)
from .blackout import GNSS_DERIVED_FIELDS
from .dead_reckoning import (
    MAX_ALLOWED_DT_S,
    PHONE_NAVIGATION_FIELDS,
    PhoneInitialization,
    RawDRPrediction,
    build_phone_initialization,
)
from .evaluation import local_xy_to_geodetic
from .motion_state import MotionState, MotionStateDetector, MotionStateSettings
from .signal_conditioning import CausalLowPassFilter


PHASE4_ALGORITHM = "calibrated_classical_dr_v1"
PHASE4_VARIANTS: tuple[str, ...] = (
    "V1_ORIENTATION_ALIGNMENT",
    "V2_ORIENTATION_PLUS_CONDITIONING",
    "V3_HEADING_STABILIZED",
    "V4_MOTION_AWARE",
    "V5_PHASE4_COMBINED",
)

CALIBRATED_SENSOR_FIELDS: tuple[str, ...] = (
    "elapsed_s",
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

REFERENCE_ONLY_FIELDS: frozenset[str] = frozenset(
    {
        "latitude_deg",
        "longitude_deg",
        "velocity_kmh",
        "heading_deg",
        "yaw_rate_degps",
        "longitudinal_acceleration_g",
        "lateral_acceleration_g",
        "is_blackout",
        "runtime_elapsed_s",
    }
)


@dataclass(frozen=True)
class Phase4Settings:
    calibration_window_s: float
    moving_speed_threshold_mps: float
    minimum_yaw_anchors: int
    maximum_yaw_dispersion_deg: float
    low_pass_cutoff_hz: float
    gyro_yaw_axis: str
    gyro_course_scale: float
    heading_correction_time_constant_s: float
    magnetic_min_ut: float
    magnetic_max_ut: float
    magnetic_max_rate_utps: float
    orientation_max_rate_degps: float
    heading_max_innovation_deg: float
    minimum_bias_samples: int
    maximum_accel_bias_mps2: float
    maximum_gyro_bias_radps: float
    max_allowed_dt_s: float
    motion: MotionStateSettings

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "Phase4Settings":
        motion = values["motion_state"]
        heading = values["heading"]
        magnetic = values["magnetometer"]
        bias = values["bias"]
        filtering = values["filtering"]
        calibration = values["calibration"]
        return cls(
            calibration_window_s=float(calibration["window_s"]),
            moving_speed_threshold_mps=float(calibration["moving_speed_threshold_mps"]),
            minimum_yaw_anchors=int(calibration["minimum_yaw_anchors"]),
            maximum_yaw_dispersion_deg=float(calibration["maximum_yaw_dispersion_deg"]),
            low_pass_cutoff_hz=float(filtering["cutoff_hz"]),
            gyro_yaw_axis=str(heading["gyro_yaw_axis"]).lower(),
            gyro_course_scale=float(heading["gyro_course_scale"]),
            heading_correction_time_constant_s=float(heading["correction_time_constant_s"]),
            magnetic_min_ut=float(magnetic["plausible_min_ut"]),
            magnetic_max_ut=float(magnetic["plausible_max_ut"]),
            magnetic_max_rate_utps=float(magnetic["maximum_magnitude_rate_utps"]),
            orientation_max_rate_degps=float(magnetic["maximum_orientation_rate_degps"]),
            heading_max_innovation_deg=float(magnetic["maximum_heading_innovation_deg"]),
            minimum_bias_samples=int(bias["minimum_stationary_samples"]),
            maximum_accel_bias_mps2=float(bias["maximum_accel_bias_mps2"]),
            maximum_gyro_bias_radps=float(bias["maximum_gyro_bias_radps"]),
            max_allowed_dt_s=float(values.get("maximum_dt_s", MAX_ALLOWED_DT_S)),
            motion=MotionStateSettings(
                window_s=float(motion["window_s"]),
                enter_accel_rms_mps2=float(motion["enter_accel_rms_mps2"]),
                exit_accel_rms_mps2=float(motion["exit_accel_rms_mps2"]),
                enter_gyro_rms_radps=float(motion["enter_gyro_rms_radps"]),
                exit_gyro_rms_radps=float(motion["exit_gyro_rms_radps"]),
                gravity_tolerance_mps2=float(motion["gravity_tolerance_mps2"]),
                enter_persistence_s=float(motion["enter_persistence_s"]),
                exit_persistence_s=float(motion["exit_persistence_s"]),
            ),
        )


@dataclass(frozen=True)
class Phase4Calibration:
    initialization: PhoneInitialization
    blackout_start_s: float
    calibration_start_s: float
    calibration_end_s_exclusive: float
    calibration_sensor_samples: int
    calibration_gnss_rows: int
    distinct_gnss_solution_rows: int
    valid_moving_yaw_anchors: int
    mounting_yaw_offset_deg: float
    yaw_dispersion_deg: float | None
    yaw_resultant_length: float | None
    yaw_calibration_reliable: bool
    yaw_fallback_reason: str | None
    initial_calibrated_heading_deg: float
    accelerometer_bias_forward_mps2: float
    accelerometer_bias_left_mps2: float
    gyroscope_bias_radps: float
    bias_stationary_samples: int
    bias_calibration_reliable: bool
    gyro_axis_verification_interval_count: int
    gyro_axis_course_correlations: dict[str, float | None]
    gyro_axis_course_scales: dict[str, float | None]
    configured_gyro_axis: str
    configured_gyro_course_scale: float
    last_sensor_elapsed_s: float
    last_magnetic_magnitude_ut: float
    last_orientation_azimuth_deg: float

    def to_dict(self) -> dict[str, Any]:
        values = asdict(self)
        values["initialization"] = self.initialization.to_dict()
        return values


@dataclass(frozen=True)
class CalibratedDRPrediction:
    data: pd.DataFrame
    initialization: PhoneInitialization
    calibration: Phase4Calibration
    variant: str
    algorithm: str = PHASE4_ALGORITHM
    integration_method: str = "causal conditioning and trapezoidal integration with motion constraints"
    coordinate_frame: str = "local ENU: x East, y North, z Up; vehicle forward/left/up intermediate"


def _reject_reference_columns(frame: pd.DataFrame, context: str) -> None:
    leaked = REFERENCE_ONLY_FIELDS.intersection(frame.columns)
    if leaked:
        raise ValueError(f"{context} contains evaluation-reference fields: {sorted(leaked)}")


def _vehicle_components(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    acceleration = frame[
        [f"accelerometer_{axis}_mps2" for axis in "xyz"]
    ].to_numpy(dtype=float)
    gravity = frame[[f"gravity_{axis}_mps2" for axis in "xyz"]].to_numpy(dtype=float)
    linear = acceleration - gravity
    forward, left, up = gravity_vehicle_basis(gravity)
    components = np.column_stack(
        (
            np.sum(linear * forward, axis=1),
            np.sum(linear * left, axis=1),
            np.sum(linear * up, axis=1),
        )
    )
    return components, gravity, up, linear


def _distinct_navigation_rows(gnss_history: pd.DataFrame) -> pd.DataFrame:
    navigation = gnss_history.loc[:, list(PHONE_NAVIGATION_FIELDS)]
    changed = navigation.ne(navigation.shift()).any(axis=1)
    if len(changed):
        changed.iloc[0] = False
    return gnss_history.loc[changed].copy()


def _gyro_axis_verification(
    sensor_history: pd.DataFrame,
    moving_anchors: pd.DataFrame,
) -> tuple[int, dict[str, float | None], dict[str, float | None]]:
    pairs: list[tuple[float, np.ndarray]] = []
    anchors = moving_anchors.sort_values("elapsed_s").reset_index(drop=True)
    for index in range(1, len(anchors)):
        first = anchors.iloc[index - 1]
        second = anchors.iloc[index]
        segment = sensor_history.loc[
            (sensor_history["elapsed_s"] > float(first["elapsed_s"]))
            & (sensor_history["elapsed_s"] <= float(second["elapsed_s"]))
        ]
        if segment.empty:
            continue
        times = segment["elapsed_s"].to_numpy(dtype=float)
        dt = np.diff(times, prepend=float(first["elapsed_s"]))
        if np.any(dt <= 0):
            continue
        gyro = segment[
            [f"gyroscope_{axis}_radps" for axis in "xyz"]
        ].to_numpy(dtype=float)
        integrated_deg = np.degrees(np.sum(gyro * dt[:, None], axis=0))
        course_change = float(
            signed_angle_difference_deg(
                float(second["gps_orientation_deg"]),
                float(first["gps_orientation_deg"]),
            )
        )
        pairs.append((course_change, integrated_deg))
    correlations: dict[str, float | None] = {axis: None for axis in "xyz"}
    scales: dict[str, float | None] = {axis: None for axis in "xyz"}
    if len(pairs) >= 2:
        course = np.array([pair[0] for pair in pairs], dtype=float)
        integrated = np.vstack([pair[1] for pair in pairs])
        for axis_index, axis in enumerate("xyz"):
            candidate = integrated[:, axis_index]
            if np.std(course) > 1e-9 and np.std(candidate) > 1e-9:
                correlations[axis] = float(np.corrcoef(course, candidate)[0, 1])
            denominator = float(np.dot(candidate, candidate))
            if denominator > 1e-9:
                scales[axis] = float(np.dot(candidate, course) / denominator)
    return len(pairs), correlations, scales


def _estimate_stationary_bias(
    sensor_window: pd.DataFrame,
    settings: Phase4Settings,
) -> tuple[float, float, float, int, bool]:
    components, gravity, _, _ = _vehicle_components(sensor_window)
    gyro = sensor_window[
        [f"gyroscope_{axis}_radps" for axis in "xyz"]
    ].to_numpy(dtype=float)
    elapsed = sensor_window["elapsed_s"].to_numpy(dtype=float)
    median_dt = float(np.median(np.diff(elapsed))) if len(elapsed) > 1 else 0.1
    dt = np.diff(elapsed, prepend=elapsed[0] - median_dt)
    detector = MotionStateDetector(settings.motion)
    stationary: list[int] = []
    for index in range(len(sensor_window)):
        observation = detector.update(
            float(np.hypot(components[index, 0], components[index, 1])),
            float(np.linalg.norm(gyro[index])),
            float(np.linalg.norm(gravity[index])),
            float(dt[index]),
        )
        if observation.state is MotionState.LIKELY_STATIONARY:
            stationary.append(index)
    reliable = len(stationary) >= settings.minimum_bias_samples
    if not reliable:
        return 0.0, 0.0, 0.0, len(stationary), False
    accel_bias = np.median(components[stationary, :2], axis=0)
    gyro_index = "xyz".index(settings.gyro_yaw_axis)
    gyro_bias = float(np.median(gyro[stationary, gyro_index]))
    if (
        np.any(np.abs(accel_bias) > settings.maximum_accel_bias_mps2)
        or abs(gyro_bias) > settings.maximum_gyro_bias_radps
    ):
        return 0.0, 0.0, 0.0, len(stationary), False
    return float(accel_bias[0]), float(accel_bias[1]), gyro_bias, len(stationary), True


def build_phase4_calibration(
    sensor_history: pd.DataFrame,
    gnss_history: pd.DataFrame,
    blackout_start_s: float,
    settings: Phase4Settings,
) -> Phase4Calibration:
    """Calibrate only from runtime sensors and phone GNSS strictly before loss."""

    _reject_reference_columns(sensor_history, "Sensor calibration history")
    _reject_reference_columns(gnss_history, "Phone GNSS calibration history")
    forbidden_sensor = set(GNSS_DERIVED_FIELDS).intersection(sensor_history.columns)
    if forbidden_sensor:
        raise ValueError(f"Sensor history exposes phone GNSS fields: {sorted(forbidden_sensor)}")
    if sensor_history.empty or gnss_history.empty:
        raise ValueError("Pre-blackout sensor and phone GNSS histories are required.")
    if bool((sensor_history["elapsed_s"] >= blackout_start_s).any()) or bool(
        (gnss_history["elapsed_s"] >= blackout_start_s).any()
    ):
        raise ValueError("Calibration history contains blackout or future samples.")
    missing = set(CALIBRATED_SENSOR_FIELDS).difference(sensor_history.columns)
    if missing:
        raise ValueError(f"Calibration sensor fields are missing: {sorted(missing)}")
    base_initialization = build_phone_initialization(
        sensor_history, gnss_history, blackout_start_s
    )
    calibration_start = max(
        float(sensor_history["elapsed_s"].iloc[0]),
        float(blackout_start_s - settings.calibration_window_s),
    )
    sensor_window = sensor_history.loc[
        sensor_history["elapsed_s"] >= calibration_start
    ].sort_values("elapsed_s").reset_index(drop=True)
    gnss_window = gnss_history.loc[
        gnss_history["elapsed_s"] >= calibration_start
    ].sort_values("elapsed_s").reset_index(drop=True)
    distinct = _distinct_navigation_rows(gnss_history)
    distinct_window = distinct.loc[distinct["elapsed_s"] >= calibration_start].copy()
    moving = distinct_window.loc[
        distinct_window["gps_speed_mps"] >= settings.moving_speed_threshold_mps
    ].copy()
    sensor_by_time = sensor_history.set_index("elapsed_s", drop=False)
    offsets: list[float] = []
    valid_moving_rows: list[int] = []
    for row_index, row in moving.iterrows():
        elapsed = float(row["elapsed_s"])
        if elapsed not in sensor_by_time.index:
            continue
        sensor = sensor_by_time.loc[elapsed]
        if isinstance(sensor, pd.DataFrame):
            sensor = sensor.iloc[-1]
        offsets.append(
            float(
                signed_angle_difference_deg(
                    float(row["gps_orientation_deg"]),
                    float(sensor["orientation_azimuth_deg"]),
                )
            )
        )
        valid_moving_rows.append(row_index)
    yaw_reliable = False
    yaw_dispersion: float | None = None
    yaw_resultant: float | None = None
    fallback_reason: str | None = None
    if offsets:
        yaw_offset, yaw_dispersion, yaw_resultant = circular_mean_deg(offsets)
        yaw_offset = float(signed_angle_difference_deg(yaw_offset, 0.0))
        yaw_reliable = (
            len(offsets) >= settings.minimum_yaw_anchors
            and yaw_dispersion <= settings.maximum_yaw_dispersion_deg
        )
    else:
        yaw_offset = 0.0
    if not yaw_reliable:
        change_elapsed = base_initialization.solution_change_elapsed_s
        change_sensor = sensor_by_time.loc[change_elapsed]
        if isinstance(change_sensor, pd.DataFrame):
            change_sensor = change_sensor.iloc[-1]
        yaw_offset = float(
            signed_angle_difference_deg(
                base_initialization.initial_heading_deg,
                float(change_sensor["orientation_azimuth_deg"]),
            )
        )
        fallback_reason = (
            "single latest phone-GNSS course/azimuth anchor; robust moving-anchor "
            "count or dispersion requirement was not met"
        )
    latest_sensor = sensor_window.iloc[-1]
    initial_heading = float(
        wrap_degrees(float(latest_sensor["orientation_azimuth_deg"]) + yaw_offset)
    )
    initialization = replace(
        base_initialization,
        initial_heading_deg=initial_heading,
        heading_source=(
            "pre-blackout robust phone-GNSS course minus exported azimuth"
            if yaw_reliable
            else "pre-blackout single course/azimuth anchor propagated by exported azimuth"
        ),
        initial_acceleration_east_mps2=0.0,
        initial_acceleration_north_mps2=0.0,
    )
    moving_valid = moving.loc[valid_moving_rows] if valid_moving_rows else moving.iloc[0:0]
    interval_count, correlations, scales = _gyro_axis_verification(
        sensor_history, moving_valid
    )
    bias_forward, bias_left, gyro_bias, bias_count, bias_reliable = _estimate_stationary_bias(
        sensor_window, settings
    )
    last_mag = latest_sensor[
        [f"magnetic_field_{axis}_ut" for axis in "xyz"]
    ].to_numpy(dtype=float)
    return Phase4Calibration(
        initialization=initialization,
        blackout_start_s=float(blackout_start_s),
        calibration_start_s=float(calibration_start),
        calibration_end_s_exclusive=float(blackout_start_s),
        calibration_sensor_samples=int(len(sensor_window)),
        calibration_gnss_rows=int(len(gnss_window)),
        distinct_gnss_solution_rows=int(len(distinct_window)),
        valid_moving_yaw_anchors=int(len(offsets)),
        mounting_yaw_offset_deg=float(yaw_offset),
        yaw_dispersion_deg=yaw_dispersion,
        yaw_resultant_length=yaw_resultant,
        yaw_calibration_reliable=bool(yaw_reliable),
        yaw_fallback_reason=fallback_reason,
        initial_calibrated_heading_deg=initial_heading,
        accelerometer_bias_forward_mps2=bias_forward,
        accelerometer_bias_left_mps2=bias_left,
        gyroscope_bias_radps=gyro_bias,
        bias_stationary_samples=bias_count,
        bias_calibration_reliable=bias_reliable,
        gyro_axis_verification_interval_count=interval_count,
        gyro_axis_course_correlations=correlations,
        gyro_axis_course_scales=scales,
        configured_gyro_axis=settings.gyro_yaw_axis,
        configured_gyro_course_scale=settings.gyro_course_scale,
        last_sensor_elapsed_s=float(latest_sensor["elapsed_s"]),
        last_magnetic_magnitude_ut=float(np.linalg.norm(last_mag)),
        last_orientation_azimuth_deg=float(latest_sensor["orientation_azimuth_deg"]),
    )


def _variant_flags(variant: str) -> tuple[bool, bool, bool, bool, bool]:
    if variant not in PHASE4_VARIANTS:
        raise ValueError(f"Unknown Phase 4 variant: {variant}")
    bias_handling = variant != "V1_ORIENTATION_ALIGNMENT"
    filtering = variant != "V1_ORIENTATION_ALIGNMENT"
    gyro_heading = variant in {
        "V3_HEADING_STABILIZED",
        "V4_MOTION_AWARE",
        "V5_PHASE4_COMBINED",
    }
    motion_aware = variant in {"V4_MOTION_AWARE", "V5_PHASE4_COMBINED"}
    complementary_correction = variant == "V5_PHASE4_COMBINED"
    return bias_handling, filtering, gyro_heading, motion_aware, complementary_correction


def integrate_calibrated_dead_reckoning(
    blackout_sensor_data: pd.DataFrame,
    calibration: Phase4Calibration,
    settings: Phase4Settings,
    variant: str = "V5_PHASE4_COMBINED",
) -> CalibratedDRPrediction:
    """Run one frozen classical ablation using no reference or future GNSS."""

    bias_handling, filtering, gyro_heading, motion_aware, complementary = _variant_flags(
        variant
    )
    _reject_reference_columns(blackout_sensor_data, "Estimator input")
    forbidden = set(GNSS_DERIVED_FIELDS).intersection(blackout_sensor_data.columns)
    if forbidden:
        raise ValueError(f"Estimator input contains forbidden GNSS fields: {sorted(forbidden)}")
    missing = set(CALIBRATED_SENSOR_FIELDS).difference(blackout_sensor_data.columns)
    if missing:
        raise ValueError(f"Estimator sensor fields are missing: {sorted(missing)}")
    if "gnss_available" in blackout_sensor_data and bool(
        blackout_sensor_data["gnss_available"].any()
    ):
        raise ValueError("Estimator input contains GNSS-available samples.")
    frame = blackout_sensor_data.reset_index(drop=True)
    if frame.empty:
        raise ValueError("Blackout sensor data cannot be empty.")
    numeric = frame.loc[:, list(CALIBRATED_SENSOR_FIELDS)].to_numpy(dtype=float)
    if not np.all(np.isfinite(numeric)):
        raise ValueError("Estimator inputs contain NaN or infinity.")
    elapsed = frame["elapsed_s"].to_numpy(dtype=float)
    dt = np.diff(elapsed, prepend=calibration.last_sensor_elapsed_s)
    if np.any(dt <= 0):
        raise ValueError("Estimator timestamps and calibration must be strictly increasing.")
    if np.any(dt > settings.max_allowed_dt_s):
        raise ValueError(f"Estimator timestamp gap exceeds {settings.max_allowed_dt_s:.3f} s.")

    components, gravity, _, _ = _vehicle_components(frame)
    gyro = frame[[f"gyroscope_{axis}_radps" for axis in "xyz"]].to_numpy(dtype=float)
    magnetic = frame[[f"magnetic_field_{axis}_ut" for axis in "xyz"]].to_numpy(dtype=float)
    magnetic_norm = np.linalg.norm(magnetic, axis=1)
    azimuth = frame["orientation_azimuth_deg"].to_numpy(dtype=float)
    bias = np.array(
        [
            calibration.accelerometer_bias_forward_mps2,
            calibration.accelerometer_bias_left_mps2,
        ]
    )
    unbiased = components[:, :2] - bias if bias_handling else components[:, :2].copy()
    low_pass = CausalLowPassFilter(settings.low_pass_cutoff_hz, 2)
    conditioned = np.empty_like(unbiased)
    for index in range(len(frame)):
        conditioned[index] = (
            low_pass.update(unbiased[index], float(dt[index]))
            if filtering
            else unbiased[index]
        )

    heading = float(calibration.initial_calibrated_heading_deg)
    speed = calibration.initialization.initial_speed_mps
    heading_rad = np.radians(heading)
    velocity = np.array([speed * np.sin(heading_rad), speed * np.cos(heading_rad)])
    position = np.zeros(2, dtype=float)
    previous_acceleration = np.zeros(2, dtype=float)
    gyro_axis_index = "xyz".index(settings.gyro_yaw_axis)
    detector = MotionStateDetector(settings.motion)
    previous_mag = calibration.last_magnetic_magnitude_ut
    previous_azimuth = calibration.last_orientation_azimuth_deg

    positions = np.empty((len(frame), 2), dtype=float)
    velocities = np.empty((len(frame), 2), dtype=float)
    local_acceleration = np.empty((len(frame), 3), dtype=float)
    orientation_heading = np.empty(len(frame), dtype=float)
    gyro_heading_values = np.empty(len(frame), dtype=float)
    final_heading = np.empty(len(frame), dtype=float)
    yaw_rate_course = np.empty(len(frame), dtype=float)
    magnetic_reliable = np.zeros(len(frame), dtype=bool)
    motion_states: list[str] = []
    zupt_applied = np.zeros(len(frame), dtype=bool)
    accel_rms = np.empty(len(frame), dtype=float)
    gyro_rms = np.empty(len(frame), dtype=float)

    for index, delta_t in enumerate(dt):
        orientation_candidate = float(
            wrap_degrees(azimuth[index] + calibration.mounting_yaw_offset_deg)
        )
        orientation_heading[index] = orientation_candidate
        course_rate = settings.gyro_course_scale * (
            gyro[index, gyro_axis_index] - calibration.gyroscope_bias_radps
        )
        yaw_rate_course[index] = course_rate
        if gyro_heading:
            heading = float(wrap_degrees(heading + np.degrees(course_rate * delta_t)))
        else:
            heading = orientation_candidate
        gyro_heading_values[index] = heading

        mag_rate = abs(magnetic_norm[index] - previous_mag) / delta_t
        orientation_rate = abs(
            float(signed_angle_difference_deg(azimuth[index], previous_azimuth))
        ) / delta_t
        innovation = float(signed_angle_difference_deg(orientation_candidate, heading))
        reliable = (
            settings.magnetic_min_ut <= magnetic_norm[index] <= settings.magnetic_max_ut
            and mag_rate <= settings.magnetic_max_rate_utps
            and orientation_rate <= settings.orientation_max_rate_degps
            and abs(innovation) <= settings.heading_max_innovation_deg
        )
        magnetic_reliable[index] = reliable
        if complementary and reliable:
            gain = 1.0 - np.exp(-delta_t / settings.heading_correction_time_constant_s)
            heading = float(wrap_degrees(heading + gain * innovation))
        final_heading[index] = heading
        previous_mag = float(magnetic_norm[index])
        previous_azimuth = float(azimuth[index])

        horizontal_raw = float(np.hypot(unbiased[index, 0], unbiased[index, 1]))
        motion_observation = detector.update(
            horizontal_raw,
            float(np.linalg.norm(gyro[index])),
            float(np.linalg.norm(gravity[index])),
            float(delta_t),
        )
        motion_states.append(motion_observation.state.value)
        accel_rms[index] = motion_observation.accel_rms_mps2
        gyro_rms[index] = motion_observation.gyro_rms_radps

        course_rad = np.radians(heading)
        forward_nav = np.array([np.sin(course_rad), np.cos(course_rad)])
        left_nav = np.array([-np.cos(course_rad), np.sin(course_rad)])
        current_acceleration = (
            conditioned[index, 0] * forward_nav + conditioned[index, 1] * left_nav
        )
        stationary = motion_aware and motion_observation.state is MotionState.LIKELY_STATIONARY
        if stationary:
            # A confirmed stationary state is a physical constraint: no
            # displacement or velocity is accumulated until hysteresis exits.
            velocity = np.zeros(2, dtype=float)
            current_acceleration = np.zeros(2, dtype=float)
            previous_acceleration = np.zeros(2, dtype=float)
            zupt_applied[index] = True
        else:
            next_velocity = velocity + 0.5 * (
                previous_acceleration + current_acceleration
            ) * delta_t
            if motion_aware:
                # Wheeled-road-vehicle non-holonomic constraint: absent a
                # detected reverse transition or tyre-slip sensor, velocity
                # is along the estimated forward axis rather than accumulating
                # unbounded lateral IMU vibration as sideslip.
                forward_speed = float(np.dot(next_velocity, forward_nav))
                next_velocity = forward_speed * forward_nav
            position = position + 0.5 * (velocity + next_velocity) * delta_t
            velocity = next_velocity
            previous_acceleration = current_acceleration
        positions[index] = position
        velocities[index] = velocity
        local_acceleration[index, :2] = current_acceleration
        local_acceleration[index, 2] = components[index, 2]

    latitude, longitude = local_xy_to_geodetic(
        positions[:, 0],
        positions[:, 1],
        calibration.initialization.origin_latitude_deg,
        calibration.initialization.origin_longitude_deg,
    )
    output = pd.DataFrame(
        {
            "elapsed_s": elapsed,
            "dt_s": dt,
            "estimated_x_m": positions[:, 0],
            "estimated_y_m": positions[:, 1],
            "estimated_velocity_x_mps": velocities[:, 0],
            "estimated_velocity_y_mps": velocities[:, 1],
            "estimated_speed_mps": np.linalg.norm(velocities, axis=1),
            "local_acceleration_x_mps2": local_acceleration[:, 0],
            "local_acceleration_y_mps2": local_acceleration[:, 1],
            "local_acceleration_z_mps2": local_acceleration[:, 2],
            "raw_forward_acceleration_mps2": components[:, 0],
            "raw_left_acceleration_mps2": components[:, 1],
            "conditioned_forward_acceleration_mps2": conditioned[:, 0],
            "conditioned_left_acceleration_mps2": conditioned[:, 1],
            "orientation_heading_deg": orientation_heading,
            "gyro_propagated_heading_deg": gyro_heading_values,
            "stabilized_heading_deg": final_heading,
            "gyro_course_rate_radps": yaw_rate_course,
            "magnetic_magnitude_ut": magnetic_norm,
            "magnetic_heading_reliable": magnetic_reliable,
            "motion_state": motion_states,
            "zupt_applied": zupt_applied,
            "motion_accel_rms_mps2": accel_rms,
            "motion_gyro_rms_radps": gyro_rms,
            "orientation_azimuth_deg": frame["orientation_azimuth_deg"].to_numpy(),
            "orientation_pitch_deg": frame["orientation_pitch_deg"].to_numpy(),
            "orientation_roll_deg": frame["orientation_roll_deg"].to_numpy(),
            "estimated_latitude_deg": latitude,
            "estimated_longitude_deg": longitude,
        }
    )
    if not np.all(np.isfinite(output.select_dtypes(include=[np.number]).to_numpy())):
        raise FloatingPointError("Calibrated DR produced non-finite state.")
    return CalibratedDRPrediction(
        data=output,
        initialization=calibration.initialization,
        calibration=calibration,
        variant=variant,
    )


def phase4_sensor_diagnostics(
    blackout_sensor_data: pd.DataFrame,
    calibration: Phase4Calibration,
    prediction: CalibratedDRPrediction,
) -> dict[str, Any]:
    """Summarize runtime-only attitude, magnetic, calibration, and motion evidence."""

    gravity = blackout_sensor_data[
        [f"gravity_{axis}_mps2" for axis in "xyz"]
    ].to_numpy(dtype=float)
    attitude = gravity_euler_diagnostics(
        gravity,
        blackout_sensor_data["orientation_azimuth_deg"].to_numpy(dtype=float),
        blackout_sensor_data["orientation_pitch_deg"].to_numpy(dtype=float),
        blackout_sensor_data["orientation_roll_deg"].to_numpy(dtype=float),
    )
    magnetic = prediction.data["magnetic_magnitude_ut"].to_numpy(dtype=float)
    stationary = prediction.data["zupt_applied"].to_numpy(dtype=bool)
    dt = prediction.data["dt_s"].to_numpy(dtype=float)
    return {
        "gravity_magnitude_mean_mps2": float(np.mean(attitude["gravity_magnitude_mps2"])),
        "gravity_magnitude_std_mps2": float(np.std(attitude["gravity_magnitude_mps2"])),
        "gravity_tilt_median_deg": float(np.median(attitude["gravity_tilt_deg"])),
        "euler_implied_tilt_median_deg": float(np.median(attitude["euler_implied_tilt_deg"])),
        "gravity_euler_disagreement_median_deg": float(
            np.median(attitude["gravity_euler_disagreement_deg"])
        ),
        "mounting_yaw_offset_deg": calibration.mounting_yaw_offset_deg,
        "yaw_calibration_dispersion_deg": calibration.yaw_dispersion_deg,
        "yaw_calibration_reliable": calibration.yaw_calibration_reliable,
        "yaw_calibration_anchor_count": calibration.valid_moving_yaw_anchors,
        "accelerometer_bias_forward_mps2": calibration.accelerometer_bias_forward_mps2,
        "accelerometer_bias_left_mps2": calibration.accelerometer_bias_left_mps2,
        "gyroscope_bias_radps": calibration.gyroscope_bias_radps,
        "bias_calibration_reliable": calibration.bias_calibration_reliable,
        "magnetic_magnitude_mean_ut": float(np.mean(magnetic)),
        "magnetic_magnitude_std_ut": float(np.std(magnetic)),
        "magnetic_magnitude_min_ut": float(np.min(magnetic)),
        "magnetic_magnitude_max_ut": float(np.max(magnetic)),
        "magnetic_reliable_fraction": float(
            prediction.data["magnetic_heading_reliable"].mean()
        ),
        "stationary_detection_samples": int(np.count_nonzero(stationary)),
        "stationary_duration_s": float(np.sum(dt[stationary])),
        "gnss_initialization_age_s": calibration.initialization.gnss_observation_age_s,
        "gnss_solution_change_age_s": calibration.initialization.gnss_solution_change_age_s,
        "calibration_start_s": calibration.calibration_start_s,
        "calibration_end_s_exclusive": calibration.calibration_end_s_exclusive,
        "calibration_sensor_samples": calibration.calibration_sensor_samples,
        "calibration_gnss_rows": calibration.calibration_gnss_rows,
        "gyro_axis_verification_interval_count": calibration.gyro_axis_verification_interval_count,
        "gyro_axis_course_correlations": calibration.gyro_axis_course_correlations,
        "gyro_axis_course_scales": calibration.gyro_axis_course_scales,
    }


def as_raw_prediction(prediction: CalibratedDRPrediction) -> RawDRPrediction:
    """Adapt a completed Phase 4 prediction to the existing evaluation API."""

    return RawDRPrediction(
        data=prediction.data,
        initialization=prediction.initialization,
        algorithm=f"{PHASE4_ALGORITHM}:{prediction.variant}",
        integration_method=prediction.integration_method,
        coordinate_frame=prediction.coordinate_frame,
    )
