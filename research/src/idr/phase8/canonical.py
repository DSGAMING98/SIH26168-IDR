"""Strict Phase 8 runtime/reference types.

Adapters deliberately return runtime and reference objects separately.  An
estimator receives only :class:`RuntimeBlackout`; the hidden reference can be
accepted only by evaluation code after prediction is complete.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np
import pandas as pd


SENSOR_FIELDS: tuple[str, ...] = (
    "elapsed_s",
    "timestamp_utc_ms",
    *(f"accelerometer_{axis}_mps2" for axis in "xyz"),
    *(f"gyroscope_{axis}_radps" for axis in "xyz"),
    *(f"magnetic_field_{axis}_ut" for axis in "xyz"),
)
OPTIONAL_SENSOR_FIELDS: tuple[str, ...] = (
    *(f"gravity_{axis}_mps2" for axis in "xyz"),
    "orientation_azimuth_deg",
    "orientation_pitch_deg",
    "orientation_roll_deg",
)
GNSS_FIELDS: tuple[str, ...] = (
    "elapsed_s",
    "timestamp_utc_ms",
    "gps_latitude_deg",
    "gps_longitude_deg",
    "gps_speed_mps",
    "gps_orientation_deg",
)
OPTIONAL_GNSS_FIELDS: tuple[str, ...] = ("gps_altitude_m", "gps_accuracy_m")
REFERENCE_FIELDS: tuple[str, ...] = (
    "elapsed_s",
    "timestamp_utc_ms",
    "latitude_deg",
    "longitude_deg",
    "speed_mps",
    "bearing_deg",
)
OPTIONAL_REFERENCE_FIELDS: tuple[str, ...] = ("altitude_m",)
REFERENCE_NAMES: frozenset[str] = frozenset(
    {"latitude_deg", "longitude_deg", "speed_mps", "bearing_deg", "reference"}
)


def _validated(
    frame: pd.DataFrame,
    required: tuple[str, ...],
    name: str,
    optional: tuple[str, ...] = (),
) -> pd.DataFrame:
    missing = set(required).difference(frame.columns)
    if missing:
        raise ValueError(f"{name} is missing fields: {sorted(missing)}")
    columns = list(required) + [column for column in optional if column in frame.columns]
    result = frame.loc[:, columns].copy().sort_values("elapsed_s").reset_index(drop=True)
    numeric = result.select_dtypes(include=[np.number]).to_numpy(dtype=float)
    if result.empty or not np.all(np.isfinite(numeric)):
        raise ValueError(f"{name} must be non-empty and finite.")
    elapsed = result["elapsed_s"].to_numpy(dtype=float)
    if np.any(np.diff(elapsed) <= 0):
        raise ValueError(f"{name} timestamps must be strictly increasing.")
    return result


@dataclass(frozen=True)
class CanonicalRuntimeSession:
    """Runtime-safe phone observations; contains no evaluation reference."""

    sensor_data: pd.DataFrame
    gnss_data: pd.DataFrame
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        leaked = REFERENCE_NAMES.intersection(self.sensor_data.columns)
        if leaked:
            raise ValueError(f"Runtime sensors expose reference fields: {sorted(leaked)}")
        sensors = _validated(self.sensor_data, SENSOR_FIELDS, "Runtime sensor data", OPTIONAL_SENSOR_FIELDS)
        gnss = _validated(self.gnss_data, GNSS_FIELDS, "Runtime GNSS data", OPTIONAL_GNSS_FIELDS)
        if float(gnss["elapsed_s"].iloc[0]) < float(sensors["elapsed_s"].iloc[0]) - 2.0:
            raise ValueError("Runtime streams do not share a plausible time origin.")
        object.__setattr__(self, "sensor_data", sensors)
        object.__setattr__(self, "gnss_data", gnss)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class CanonicalEvaluationReference:
    """Hidden trajectory loaded separately and never passed to an estimator."""

    data: pd.DataFrame
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", _validated(self.data, REFERENCE_FIELDS, "Reference data", OPTIONAL_REFERENCE_FIELDS))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class RuntimeBlackout:
    """GNSS-free online rows plus strictly pre-blackout runtime history."""

    sensor_history: pd.DataFrame
    gnss_history: pd.DataFrame
    blackout_sensor_data: pd.DataFrame
    start_s: float
    duration_s: float
    session_id: str

    @property
    def end_s(self) -> float:
        return self.start_s + self.duration_s


def create_runtime_blackout(
    runtime: CanonicalRuntimeSession,
    *,
    start_s: float,
    duration_s: float,
) -> RuntimeBlackout:
    """Create a deterministic half-open ``start <= t < start+duration`` view."""

    if not np.isfinite(start_s) or not np.isfinite(duration_s) or duration_s <= 0:
        raise ValueError("Blackout start must be finite and duration must be positive.")
    end_s = float(start_s + duration_s)
    sensors = runtime.sensor_data
    if start_s <= float(sensors["elapsed_s"].iloc[0]) or end_s > float(sensors["elapsed_s"].iloc[-1]):
        raise ValueError("Blackout lies outside the valid runtime session.")
    before = sensors["elapsed_s"] < start_s
    active = (sensors["elapsed_s"] >= start_s) & (sensors["elapsed_s"] < end_s)
    gnss_before = runtime.gnss_data["elapsed_s"] < start_s
    if not bool(active.any()) or not bool(before.any()) or not bool(gnss_before.any()):
        raise ValueError("Blackout requires sensor rows plus pre-blackout sensor/GNSS history.")
    blackout = sensors.loc[active].copy().reset_index(drop=True)
    sensitive_gnss = set(GNSS_FIELDS).difference({"elapsed_s", "timestamp_utc_ms"})
    if sensitive_gnss.intersection(blackout.columns):
        raise ValueError("GNSS leaked into the blackout sensor view.")
    return RuntimeBlackout(
        sensor_history=sensors.loc[before].copy().reset_index(drop=True),
        gnss_history=runtime.gnss_data.loc[gnss_before].copy().reset_index(drop=True),
        blackout_sensor_data=blackout,
        start_s=float(start_s),
        duration_s=float(duration_s),
        session_id=str(runtime.metadata.get("session_id", "unknown")),
    )
