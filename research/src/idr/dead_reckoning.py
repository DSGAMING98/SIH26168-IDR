"""Leakage-resistant raw smartphone inertial dead reckoning baseline."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from .blackout import GNSS_DERIVED_FIELDS, BlackoutWindow, RuntimeDataset
from .evaluation import local_xy_to_geodetic
from .orientation import rotate_device_to_enu


RAW_DR_ALGORITHM = "raw_inertial_dr_v1"
MAX_ALLOWED_DT_S = 0.5

RAW_DR_SENSOR_FIELDS: tuple[str, ...] = (
    "elapsed_s",
    "accelerometer_x_mps2",
    "accelerometer_y_mps2",
    "accelerometer_z_mps2",
    "gravity_x_mps2",
    "gravity_y_mps2",
    "gravity_z_mps2",
    "orientation_azimuth_deg",
    "orientation_pitch_deg",
    "orientation_roll_deg",
)

PHONE_NAVIGATION_FIELDS: tuple[str, ...] = (
    "gps_latitude_deg",
    "gps_longitude_deg",
    "gps_speed_mps",
    "gps_orientation_deg",
)


@dataclass(frozen=True)
class PhoneInitialization:
    """State constructed only from legitimate pre-blackout phone observations."""

    blackout_start_s: float
    observation_elapsed_s: float
    observation_timestamp_local: str
    gnss_observation_age_s: float
    solution_change_elapsed_s: float
    solution_change_timestamp_local: str
    gnss_solution_change_age_s: float
    origin_latitude_deg: float
    origin_longitude_deg: float
    initial_speed_mps: float
    initial_heading_deg: float
    heading_source: str
    initial_acceleration_east_mps2: float
    initial_acceleration_north_mps2: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RawDRPrediction:
    """Raw DR output in a phone-GNSS-origin local ENU frame."""

    data: pd.DataFrame
    initialization: PhoneInitialization
    algorithm: str = RAW_DR_ALGORITHM
    integration_method: str = "trapezoidal acceleration and velocity integration"
    coordinate_frame: str = "local ENU: x East, y North, z Up"


def extract_blackout_sensor_data(
    runtime: RuntimeDataset,
    window: BlackoutWindow,
) -> pd.DataFrame:
    """Extract an aligned GNSS-free blackout frame from the Phase 2 runtime view."""

    sensor_data = runtime.sensor_data
    forbidden = set(GNSS_DERIVED_FIELDS).intersection(sensor_data.columns)
    if forbidden:
        raise ValueError(f"Runtime sensor data exposes forbidden GNSS fields: {sorted(forbidden)}")
    missing = set(RAW_DR_SENSOR_FIELDS).difference(sensor_data.columns)
    if missing:
        raise ValueError(f"Runtime sensor fields are missing: {sorted(missing)}")
    expected = (
        (sensor_data["elapsed_s"] >= window.start_s)
        & (sensor_data["elapsed_s"] < window.end_s)
    )
    if not bool(expected.any()):
        raise ValueError("Blackout runtime is empty.")
    if "gnss_available" not in sensor_data.columns:
        raise ValueError("Runtime sensor data lacks gnss_available.")
    if bool(sensor_data.loc[expected, "gnss_available"].any()):
        raise ValueError("Requested blackout rows are marked GNSS-available.")
    return sensor_data.loc[expected].copy().reset_index(drop=True)


def build_phone_initialization(
    sensor_history: pd.DataFrame,
    gnss_history: pd.DataFrame,
    blackout_start_s: float,
) -> PhoneInitialization:
    """Build initial state from strictly pre-blackout phone history.

    Callers must filter both frames to times earlier than ``blackout_start_s``.
    The strict validation prevents accidental future or post-blackout GNSS use.
    """

    if sensor_history.empty or gnss_history.empty:
        raise ValueError("Pre-blackout sensor and phone GNSS history are required.")
    if "elapsed_s" not in sensor_history or "elapsed_s" not in gnss_history:
        raise ValueError("Pre-blackout histories require elapsed_s.")
    if bool((sensor_history["elapsed_s"] >= blackout_start_s).any()):
        raise ValueError("Sensor history contains blackout or future samples.")
    if bool((gnss_history["elapsed_s"] >= blackout_start_s).any()):
        raise ValueError("GNSS history contains blackout or future samples.")
    missing_sensor = set(RAW_DR_SENSOR_FIELDS).difference(sensor_history.columns)
    missing_gnss = set(PHONE_NAVIGATION_FIELDS).difference(gnss_history.columns)
    if missing_sensor or missing_gnss:
        raise ValueError(
            f"Initialization fields missing: sensor={sorted(missing_sensor)}, "
            f"gnss={sorted(missing_gnss)}"
        )

    sensor_history = sensor_history.sort_values("elapsed_s").reset_index(drop=True)
    gnss_history = gnss_history.sort_values("elapsed_s").reset_index(drop=True)
    latest_sensor = sensor_history.iloc[-1]
    latest_gnss = gnss_history.iloc[-1]
    navigation = gnss_history.loc[:, list(PHONE_NAVIGATION_FIELDS)]
    numeric_navigation = navigation.to_numpy(dtype=float)
    if not np.all(np.isfinite(numeric_navigation)):
        raise ValueError("Pre-blackout phone GNSS initialization contains non-finite values.")
    changed = navigation.ne(navigation.shift()).any(axis=1).to_numpy(dtype=bool)
    change_index = int(np.flatnonzero(changed)[-1])
    solution_change_elapsed_s = float(gnss_history["elapsed_s"].iloc[change_index])

    change_sensor_matches = np.flatnonzero(
        np.isclose(
            sensor_history["elapsed_s"].to_numpy(dtype=float),
            solution_change_elapsed_s,
            rtol=0.0,
            atol=1e-9,
        )
    )
    if not change_sensor_matches.size:
        raise ValueError("GNSS solution-change timestamp is not aligned with sensor history.")
    change_sensor = sensor_history.iloc[int(change_sensor_matches[-1])]

    device_linear = np.array(
        [
            latest_sensor[f"accelerometer_{axis}_mps2"]
            - latest_sensor[f"gravity_{axis}_mps2"]
            for axis in ("x", "y", "z")
        ],
        dtype=float,
    )
    acceleration_enu = rotate_device_to_enu(
        device_linear,
        float(latest_sensor["orientation_azimuth_deg"]),
        float(latest_sensor["orientation_pitch_deg"]),
        float(latest_sensor["orientation_roll_deg"]),
    )
    observation_elapsed_s = float(latest_gnss["elapsed_s"])
    return PhoneInitialization(
        blackout_start_s=float(blackout_start_s),
        observation_elapsed_s=observation_elapsed_s,
        observation_timestamp_local=pd.Timestamp(latest_sensor["timestamp_local"]).isoformat(),
        gnss_observation_age_s=float(blackout_start_s - observation_elapsed_s),
        solution_change_elapsed_s=solution_change_elapsed_s,
        solution_change_timestamp_local=pd.Timestamp(change_sensor["timestamp_local"]).isoformat(),
        gnss_solution_change_age_s=float(blackout_start_s - solution_change_elapsed_s),
        origin_latitude_deg=float(latest_gnss["gps_latitude_deg"]),
        origin_longitude_deg=float(latest_gnss["gps_longitude_deg"]),
        initial_speed_mps=float(latest_gnss["gps_speed_mps"]),
        initial_heading_deg=float(latest_gnss["gps_orientation_deg"]),
        heading_source="latest pre-blackout phone GPS orientation/course",
        initial_acceleration_east_mps2=float(acceleration_enu[0]),
        initial_acceleration_north_mps2=float(acceleration_enu[1]),
    )


def integrate_raw_dead_reckoning(
    blackout_sensor_data: pd.DataFrame,
    initialization: PhoneInitialization,
    max_allowed_dt_s: float = MAX_ALLOWED_DT_S,
) -> RawDRPrediction:
    """Integrate raw phone acceleration over one blackout using actual timestamps."""

    if blackout_sensor_data.empty:
        raise ValueError("Blackout sensor data cannot be empty.")
    forbidden = set(GNSS_DERIVED_FIELDS).intersection(blackout_sensor_data.columns)
    if forbidden:
        raise ValueError(f"Estimator input contains forbidden GNSS fields: {sorted(forbidden)}")
    missing = set(RAW_DR_SENSOR_FIELDS).difference(blackout_sensor_data.columns)
    if missing:
        raise ValueError(f"Estimator sensor fields are missing: {sorted(missing)}")
    if "gnss_available" in blackout_sensor_data and bool(
        blackout_sensor_data["gnss_available"].any()
    ):
        raise ValueError("Estimator input contains GNSS-available samples.")
    if not np.isfinite(max_allowed_dt_s) or max_allowed_dt_s <= 0:
        raise ValueError("Maximum allowed dt must be finite and positive.")

    frame = blackout_sensor_data.reset_index(drop=True)
    numeric = frame.loc[:, list(RAW_DR_SENSOR_FIELDS)].to_numpy(dtype=float)
    if not np.all(np.isfinite(numeric)):
        raise ValueError("Estimator inputs contain NaN or infinity.")
    elapsed_s = frame["elapsed_s"].to_numpy(dtype=float)
    dt_s = np.diff(elapsed_s, prepend=initialization.observation_elapsed_s)
    if np.any(dt_s <= 0):
        raise ValueError("Estimator timestamps and initialization must be strictly increasing.")
    if np.any(dt_s > max_allowed_dt_s):
        raise ValueError(f"Estimator timestamp gap exceeds {max_allowed_dt_s:.3f} s.")

    acceleration_device = np.column_stack(
        [
            frame[f"accelerometer_{axis}_mps2"].to_numpy(dtype=float)
            - frame[f"gravity_{axis}_mps2"].to_numpy(dtype=float)
            for axis in ("x", "y", "z")
        ]
    )
    acceleration_enu = rotate_device_to_enu(
        acceleration_device,
        frame["orientation_azimuth_deg"].to_numpy(dtype=float),
        frame["orientation_pitch_deg"].to_numpy(dtype=float),
        frame["orientation_roll_deg"].to_numpy(dtype=float),
    )

    heading_rad = np.radians(initialization.initial_heading_deg)
    velocity = np.array(
        [
            initialization.initial_speed_mps * np.sin(heading_rad),
            initialization.initial_speed_mps * np.cos(heading_rad),
        ],
        dtype=float,
    )
    position = np.zeros(2, dtype=float)
    previous_acceleration = np.array(
        [
            initialization.initial_acceleration_east_mps2,
            initialization.initial_acceleration_north_mps2,
        ],
        dtype=float,
    )
    positions = np.empty((len(frame), 2), dtype=float)
    velocities = np.empty((len(frame), 2), dtype=float)
    for index, dt in enumerate(dt_s):
        current_acceleration = acceleration_enu[index, :2]
        next_velocity = velocity + 0.5 * (
            previous_acceleration + current_acceleration
        ) * dt
        position = position + 0.5 * (velocity + next_velocity) * dt
        velocity = next_velocity
        positions[index] = position
        velocities[index] = velocity
        previous_acceleration = current_acceleration

    if not np.all(np.isfinite(positions)) or not np.all(np.isfinite(velocities)):
        raise FloatingPointError("Raw DR integration produced non-finite state.")
    estimated_latitude, estimated_longitude = local_xy_to_geodetic(
        positions[:, 0],
        positions[:, 1],
        initialization.origin_latitude_deg,
        initialization.origin_longitude_deg,
    )
    output = pd.DataFrame(
        {
            "elapsed_s": elapsed_s,
            "dt_s": dt_s,
            "estimated_x_m": positions[:, 0],
            "estimated_y_m": positions[:, 1],
            "estimated_velocity_x_mps": velocities[:, 0],
            "estimated_velocity_y_mps": velocities[:, 1],
            "estimated_speed_mps": np.linalg.norm(velocities, axis=1),
            "local_acceleration_x_mps2": acceleration_enu[:, 0],
            "local_acceleration_y_mps2": acceleration_enu[:, 1],
            "local_acceleration_z_mps2": acceleration_enu[:, 2],
            "orientation_azimuth_deg": frame["orientation_azimuth_deg"],
            "orientation_pitch_deg": frame["orientation_pitch_deg"],
            "orientation_roll_deg": frame["orientation_roll_deg"],
            "estimated_latitude_deg": estimated_latitude,
            "estimated_longitude_deg": estimated_longitude,
        }
    )
    return RawDRPrediction(data=output, initialization=initialization)
