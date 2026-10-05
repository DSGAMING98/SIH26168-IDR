"""Strict reader for local Phase 9 Android recording directories.

The normalized runtime file is intentionally separate from ``gnss_raw.csv``.
Only the former is returned by :meth:`AndroidSession.to_canonical_runtime`;
physical GNSS retained for debugging cannot enter the estimator interface.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np
import pandas as pd

from idr.phase8.canonical import CanonicalRuntimeSession
from idr.phase9.schema import (
    AVAILABILITY_FIELDS,
    GNSS_DIAGNOSTIC_FIELDS,
    GNSS_SENSITIVE_FIELDS,
    GNSS_STATUSES,
    ML_OOD_STATES,
    RAW_GNSS_COLUMNS,
    RAW_IMU_COLUMNS,
    ROTATION_FIELDS,
    RUNTIME_COLUMNS,
    RUNTIME_COLUMNS_V1,
    SCHEMA_VERSION,
    SENSOR_TYPES,
    SENSOR_UNITS,
    SUPPORTED_SCHEMA_VERSIONS,
    VECTOR_FIELDS,
)


class AndroidSessionError(ValueError):
    """Recording is incomplete, inconsistent, or unsafe to replay."""


def _read_csv(path: Path, required: tuple[str, ...]) -> pd.DataFrame:
    if not path.is_file():
        raise AndroidSessionError(f"Missing recording file: {path.name}")
    frame = pd.read_csv(path)
    missing = set(required).difference(frame.columns)
    extra = set(frame.columns).difference(required)
    if missing or extra:
        raise AndroidSessionError(f"{path.name} schema mismatch; missing={sorted(missing)}, extra={sorted(extra)}")
    return frame.loc[:, required].copy()


def _bool_series(series: pd.Series, name: str) -> pd.Series:
    lowered = series.astype(str).str.strip().str.lower()
    invalid = ~lowered.isin(("true", "false"))
    if bool(invalid.any()):
        raise AndroidSessionError(f"{name} must contain only true/false")
    return lowered.eq("true")


def _strictly_increasing(series: pd.Series, name: str) -> None:
    numeric = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    if not np.all(np.isfinite(numeric)) or np.any(np.diff(numeric) <= 0):
        raise AndroidSessionError(f"{name} must be finite and strictly increasing")


@dataclass(frozen=True)
class AndroidSession:
    directory: Path
    metadata: Mapping[str, Any]
    runtime: pd.DataFrame
    raw_imu: pd.DataFrame
    raw_physical_gnss: pd.DataFrame

    @property
    def session_id(self) -> str:
        return str(self.metadata["session_id"])

    @property
    def missing_sensors(self) -> tuple[str, ...]:
        availability = self.metadata["availability"]
        return tuple(name for name in ("accelerometer", "gyroscope", "magnetometer", "gravity", "rotation_vector") if not availability[name])

    def achieved_rates_hz(self) -> dict[str, float]:
        rates: dict[str, float] = {}
        for sensor_type in sorted(SENSOR_TYPES):
            times = self.raw_imu.loc[self.raw_imu["sensor_type"] == sensor_type, "event_timestamp_ns"].to_numpy(dtype=np.int64)
            rates[sensor_type] = _rate_hz(times)
        rates["normalized"] = _rate_hz(self.runtime["monotonic_timestamp_ns"].to_numpy(dtype=np.int64))
        return rates

    def to_canonical_runtime(self) -> CanonicalRuntimeSession:
        """Create Phase 8's runtime-only type; never includes raw physical GNSS."""

        required_core = ("accelerometer", "gyroscope", "magnetometer")
        unavailable = [name for name in required_core if name in self.missing_sensors]
        if unavailable:
            raise AndroidSessionError(f"Core estimator sensors unavailable: {unavailable}")
        wall_ms = pd.to_datetime(self.runtime["wall_clock_utc"], utc=True, errors="coerce").astype("int64") / 1_000_000
        if not np.all(np.isfinite(wall_ms)):
            raise AndroidSessionError("wall_clock_utc cannot be converted for canonical compatibility")
        sensors = pd.DataFrame(
            {
                "elapsed_s": self.runtime["elapsed_seconds"].astype(float),
                "timestamp_utc_ms": wall_ms.astype(float),
                **{name: self.runtime[source].astype(float) for name, source in _canonical_sensor_mapping().items()},
            }
        )
        if not np.all(np.isfinite(sensors.to_numpy(dtype=float))):
            raise AndroidSessionError("Core runtime sensor values cannot be null")
        if "gravity" not in self.missing_sensors:
            for axis in "xyz":
                sensors[f"gravity_{axis}_mps2"] = self.runtime[f"gravity_{axis}_mps2"].astype(float)

        visible = self.runtime.loc[
            ~self.runtime["simulated_blackout"]
            & self.runtime[["gnss_latitude_deg", "gnss_longitude_deg", "gnss_speed_mps", "gnss_bearing_deg"]].notna().all(axis=1)
        ]
        if len(visible) < 2:
            raise AndroidSessionError("At least two complete runtime-visible GNSS fixes are required")
        gnss = pd.DataFrame(
            {
                "elapsed_s": visible["elapsed_seconds"].astype(float),
                "timestamp_utc_ms": pd.to_datetime(visible["wall_clock_utc"], utc=True).astype("int64") / 1_000_000,
                "gps_latitude_deg": visible["gnss_latitude_deg"].astype(float),
                "gps_longitude_deg": visible["gnss_longitude_deg"].astype(float),
                "gps_speed_mps": visible["gnss_speed_mps"].astype(float),
                "gps_orientation_deg": visible["gnss_bearing_deg"].astype(float),
            }
        )
        if visible["gnss_altitude_m"].notna().all():
            gnss["gps_altitude_m"] = visible["gnss_altitude_m"].astype(float)
        if visible["gnss_accuracy_m"].notna().all():
            gnss["gps_accuracy_m"] = visible["gnss_accuracy_m"].astype(float)
        return CanonicalRuntimeSession(sensors, gnss, {**self.metadata, "source": "android_phase9_runtime_only"})


def load_android_session(directory: str | Path, *, load_raw: bool = True) -> AndroidSession:
    root = Path(directory).resolve()
    metadata_path = root / "session_metadata.json"
    if not metadata_path.is_file():
        raise AndroidSessionError("Missing recording file: session_metadata.json")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise AndroidSessionError("Invalid session_metadata.json") from error
    _validate_metadata(metadata)
    schema_version = int(metadata["schema_version"])
    runtime_columns = RUNTIME_COLUMNS if schema_version == SCHEMA_VERSION else RUNTIME_COLUMNS_V1
    runtime = _read_csv(root / "runtime_10hz.csv", runtime_columns)
    raw_imu = _read_csv(root / "imu_raw.csv", RAW_IMU_COLUMNS) if load_raw else pd.DataFrame(columns=RAW_IMU_COLUMNS)
    raw_gnss = _read_csv(root / "gnss_raw.csv", RAW_GNSS_COLUMNS) if load_raw else pd.DataFrame(columns=RAW_GNSS_COLUMNS)
    if schema_version == 1:
        runtime = _upgrade_v1_runtime(runtime, raw_gnss, int(metadata["session_origin_monotonic_ns"]))
    runtime = _validate_runtime(runtime, metadata)
    if load_raw:
        raw_imu = _validate_raw_imu(raw_imu, int(metadata["session_origin_monotonic_ns"]))
        raw_gnss = _validate_raw_gnss(raw_gnss, int(metadata["session_origin_monotonic_ns"]))
        _validate_gnss_summary(metadata, runtime, raw_gnss)
    return AndroidSession(root, MappingProxyType(metadata), runtime, raw_imu, raw_gnss)


def _validate_metadata(metadata: dict[str, Any]) -> None:
    required = {
        "schema_version", "session_id", "session_origin_monotonic_ns", "session_start_utc",
        "timestamp_semantics", "device_frame", "units", "requested_sampling_period_us",
        "normalized_target_hz", "location_provider", "storage", "availability", "sensors",
    }
    missing = required.difference(metadata)
    if missing:
        raise AndroidSessionError(f"Metadata missing fields: {sorted(missing)}")
    if metadata["schema_version"] not in SUPPORTED_SCHEMA_VERSIONS:
        raise AndroidSessionError(f"Unsupported schema_version: {metadata['schema_version']}")
    if metadata["schema_version"] == SCHEMA_VERSION:
        diagnostics = metadata.get("gnss_diagnostics")
        required_diagnostics = {
            "physical_callback_count", "last_physical_gnss_timestamp_ns", "first_valid_fix_timestamp_ns",
            "time_to_first_fix_seconds", "gnss_status_available", "satellites_visible", "satellites_used_in_fix",
        }
        if not isinstance(diagnostics, dict) or set(diagnostics) != required_diagnostics:
            raise AndroidSessionError("Metadata GNSS diagnostics are incomplete")
    if metadata["units"] != SENSOR_UNITS:
        raise AndroidSessionError("Metadata units do not match the Phase 9 SI/WGS84 contract")
    availability = metadata["availability"]
    required_availability = {name.removesuffix("_available") for name in AVAILABILITY_FIELDS}
    if set(availability) != required_availability:
        raise AndroidSessionError("Metadata sensor availability keys are incomplete")
    if any(type(value) is not bool for value in availability.values()):
        raise AndroidSessionError("Metadata sensor availability values must be booleans")
    if metadata["location_provider"] != "gps":
        raise AndroidSessionError("Phase 9 runtime requires Android GPS_PROVIDER, not network location")
    if "no upload" not in str(metadata["storage"]).lower():
        raise AndroidSessionError("Metadata must declare local-only/no-upload storage")


def _validate_runtime(frame: pd.DataFrame, metadata: Mapping[str, Any]) -> pd.DataFrame:
    if frame.empty:
        raise AndroidSessionError("runtime_10hz.csv must contain at least one sample")
    _strictly_increasing(frame["sequence_id"], "runtime sequence_id")
    _strictly_increasing(frame["elapsed_seconds"], "runtime elapsed_seconds")
    _strictly_increasing(frame["monotonic_timestamp_ns"], "runtime monotonic_timestamp_ns")
    for column in (
        "gnss_is_fresh", "simulated_blackout", "blackout_masks_real_fix", "gnss_status_available",
        *AVAILABILITY_FIELDS,
    ):
        frame[column] = _bool_series(frame[column], column)
    sequence = pd.to_numeric(frame["sequence_id"], errors="coerce").to_numpy(dtype=float)
    if not np.all(sequence == np.arange(len(frame))):
        raise AndroidSessionError("runtime sequence_id must be contiguous from zero")
    origin = int(metadata["session_origin_monotonic_ns"])
    derived = (frame["monotonic_timestamp_ns"].to_numpy(dtype=np.int64) - origin) / 1e9
    elapsed = frame["elapsed_seconds"].to_numpy(dtype=float)
    if np.max(np.abs(derived - elapsed), initial=0.0) > 0.005:
        raise AndroidSessionError("elapsed_seconds disagrees with monotonic clock by more than 5 ms")
    if not set(frame["gnss_status"]).issubset(GNSS_STATUSES):
        raise AndroidSessionError("Unknown GNSS status")
    if not set(frame["ml_ood_state"]).issubset(ML_OOD_STATES):
        raise AndroidSessionError("Unknown ML OOD state")
    callback_count = pd.to_numeric(frame["physical_gnss_callback_count"], errors="coerce").to_numpy(dtype=float)
    if (
        not np.all(np.isfinite(callback_count))
        or np.any(callback_count < 0)
        or np.any(callback_count != np.floor(callback_count))
        or np.any(np.diff(callback_count) < 0)
    ):
        raise AndroidSessionError("physical_gnss_callback_count must be a nonnegative monotonic integer")
    frame["physical_gnss_callback_count"] = callback_count.astype(np.int64)
    _validate_first_fix_fields(frame)
    _validate_satellite_fields(frame)
    visible = frame["gnss_latitude_deg"].notna() | frame["gnss_longitude_deg"].notna()
    if bool((~frame.loc[visible, "gnss_latitude_deg"].between(-90.0, 90.0)).any()) or bool(
        (~frame.loc[visible, "gnss_longitude_deg"].between(-180.0, 180.0)).any()
    ):
        raise AndroidSessionError("Runtime GNSS coordinates are invalid")
    blackout = frame["simulated_blackout"]
    if bool(frame.loc[blackout, list(GNSS_SENSITIVE_FIELDS)].notna().any(axis=None)):
        raise AndroidSessionError("GNSS leakage: blackout runtime contains a sensitive GNSS value")
    if bool(frame.loc[blackout, "gnss_is_fresh"].any()):
        raise AndroidSessionError("GNSS leakage: blackout runtime marks a fix fresh")
    if bool((frame.loc[blackout, "gnss_status"] != "SIMULATED_BLACKOUT").any()):
        raise AndroidSessionError("Blackout rows require SIMULATED_BLACKOUT status")
    first_fix_known = frame["first_valid_gnss_fix_timestamp_ns"].notna()
    expected_real_mask = blackout & first_fix_known
    if bool((frame["blackout_masks_real_fix"] != expected_real_mask).any()):
        raise AndroidSessionError("blackout_masks_real_fix disagrees with first-fix history")
    waiting = frame["gnss_status"] == "WAITING_FOR_FIRST_FIX"
    if bool(frame.loc[waiting, list(GNSS_SENSITIVE_FIELDS)].notna().any(axis=None)):
        raise AndroidSessionError("WAITING_FOR_FIRST_FIX rows cannot expose runtime GNSS")
    for sensor, fields in VECTOR_FIELDS.items():
        availability_column = f"{sensor}_available"
        unavailable = ~frame[availability_column]
        if bool(frame.loc[unavailable, list(fields)].notna().any(axis=None)):
            raise AndroidSessionError(f"Unavailable {sensor} has fabricated values")
        expected = bool(metadata["availability"][sensor])
        if bool((frame[availability_column] != expected).any()):
            raise AndroidSessionError(f"Runtime {sensor} availability disagrees with session metadata")
    rotation_unavailable = ~frame["rotation_vector_available"]
    if bool(frame.loc[rotation_unavailable, list(ROTATION_FIELDS)].notna().any(axis=None)):
        raise AndroidSessionError("Unavailable rotation vector has fabricated values")
    if bool((frame["rotation_vector_available"] != bool(metadata["availability"]["rotation_vector"])).any()):
        raise AndroidSessionError("Runtime rotation-vector availability disagrees with session metadata")
    return frame


def _upgrade_v1_runtime(frame: pd.DataFrame, raw_gnss: pd.DataFrame, origin_ns: int) -> pd.DataFrame:
    """Retain parser/replay compatibility for Phase 9 recordings already exported from phones."""

    upgraded = frame.copy()
    upgraded["gnss_status"] = upgraded["gnss_status"].replace({"NO_FIX": "WAITING_FOR_FIRST_FIX"})
    runtime_ns = upgraded["monotonic_timestamp_ns"].to_numpy(dtype=np.int64)
    valid_raw = raw_gnss.loc[raw_gnss.get("callback_status", pd.Series(dtype=str)) != "INVALID"]
    if not valid_raw.empty:
        first_fix_ns: float | None = float(valid_raw["location_timestamp_ns"].iloc[0])
    else:
        visible = upgraded["gnss_latitude_deg"].notna() & upgraded["gnss_longitude_deg"].notna()
        first_fix_ns = float(upgraded.loc[visible, "monotonic_timestamp_ns"].iloc[0]) if bool(visible.any()) else None
    if raw_gnss.empty:
        counts = np.zeros(len(upgraded), dtype=np.int64)
        last_timestamp = np.full(len(upgraded), np.nan)
        callback_age = np.full(len(upgraded), np.nan)
    else:
        raw_ns = raw_gnss["location_timestamp_ns"].to_numpy(dtype=np.int64)
        counts = np.searchsorted(raw_ns, runtime_ns, side="right")
        last_timestamp = np.array([raw_ns[count - 1] if count else np.nan for count in counts], dtype=float)
        callback_age = np.maximum(0.0, (runtime_ns - last_timestamp) / 1e9)
    first_known = runtime_ns >= first_fix_ns if first_fix_ns is not None else np.zeros(len(upgraded), dtype=bool)
    values: dict[str, Any] = {
        "blackout_masks_real_fix": upgraded["simulated_blackout"].astype(str).str.lower().eq("true") & first_known,
        "physical_gnss_callback_count": counts,
        "latest_physical_callback_age_seconds": callback_age,
        "last_physical_gnss_timestamp_ns": last_timestamp,
        "first_valid_gnss_fix_timestamp_ns": np.where(first_known, first_fix_ns, np.nan),
        "time_to_first_fix_seconds": np.where(first_known, max(0.0, (first_fix_ns - origin_ns) / 1e9) if first_fix_ns is not None else np.nan, np.nan),
        "gnss_status_available": False,
        "satellites_visible": np.nan,
        "satellites_used_in_fix": np.nan,
    }
    insertion = list(upgraded.columns).index("simulated_blackout") + 1
    for offset, name in enumerate(GNSS_DIAGNOSTIC_FIELDS):
        upgraded.insert(insertion + offset, name, values[name])
    return upgraded.loc[:, RUNTIME_COLUMNS]


def _validate_first_fix_fields(frame: pd.DataFrame) -> None:
    fix = pd.to_numeric(frame["first_valid_gnss_fix_timestamp_ns"], errors="coerce")
    timing = pd.to_numeric(frame["time_to_first_fix_seconds"], errors="coerce")
    if bool((fix.notna() != timing.notna()).any()) or bool((timing.dropna() < 0).any()):
        raise AndroidSessionError("First-fix timestamp and timing must appear together and be nonnegative")
    if fix.dropna().nunique() > 1 or timing.dropna().nunique() > 1:
        raise AndroidSessionError("First-fix timestamp and timing must remain constant after acquisition")
    known = fix.notna()
    if bool((fix.loc[known] > frame.loc[known, "monotonic_timestamp_ns"]).any()):
        raise AndroidSessionError("First-fix timestamp cannot be in a future runtime snapshot")


def _validate_satellite_fields(frame: pd.DataFrame) -> None:
    visible = pd.to_numeric(frame["satellites_visible"], errors="coerce")
    used = pd.to_numeric(frame["satellites_used_in_fix"], errors="coerce")
    if bool((visible.notna() != used.notna()).any()):
        raise AndroidSessionError("Satellite visible/used counts must appear together")
    present = visible.notna()
    if bool((present & ~frame["gnss_status_available"]).any()):
        raise AndroidSessionError("Satellite counts require GNSS status availability")
    if bool(((visible.loc[present] < 0) | (used.loc[present] < 0) | (used.loc[present] > visible.loc[present])).any()):
        raise AndroidSessionError("Satellite counts are invalid")
    if bool(((visible.loc[present] % 1 != 0) | (used.loc[present] % 1 != 0)).any()):
        raise AndroidSessionError("Satellite counts must be integers")


def _validate_gnss_summary(metadata: Mapping[str, Any], runtime: pd.DataFrame, raw_gnss: pd.DataFrame) -> None:
    if int(metadata["schema_version"]) != SCHEMA_VERSION:
        return
    # An in-progress export still contains the metadata written when recording
    # opened, so final cross-file totals are enforced only for stopped sessions.
    if metadata.get("session_end_utc") is None:
        return
    summary = metadata["gnss_diagnostics"]
    if int(summary["physical_callback_count"]) != len(raw_gnss):
        raise AndroidSessionError("Metadata physical GNSS callback count disagrees with gnss_raw.csv")
    final = runtime.iloc[-1]
    for metadata_name, runtime_name in (
        ("first_valid_fix_timestamp_ns", "first_valid_gnss_fix_timestamp_ns"),
        ("time_to_first_fix_seconds", "time_to_first_fix_seconds"),
    ):
        expected = summary[metadata_name]
        actual = final[runtime_name]
        if expected is None and pd.isna(actual):
            continue
        if expected is None or (not pd.isna(actual) and float(expected) != float(actual)):
            raise AndroidSessionError(f"Metadata {metadata_name} disagrees with runtime stream")


def _validate_raw_imu(frame: pd.DataFrame, origin_ns: int) -> pd.DataFrame:
    if not set(frame["sensor_type"]).issubset(SENSOR_TYPES):
        raise AndroidSessionError("Unknown raw IMU sensor_type")
    _strictly_increasing(frame["logger_sequence_id"], "raw IMU logger_sequence_id")
    for name, group in frame.groupby("sensor_type"):
        _strictly_increasing(group["event_timestamp_ns"], f"raw {name} timestamps")
    _validate_elapsed_clock(frame, "event_timestamp_ns", origin_ns, "raw IMU")
    return frame


def _validate_raw_gnss(frame: pd.DataFrame, origin_ns: int) -> pd.DataFrame:
    if frame.empty:
        return frame
    _strictly_increasing(frame["logger_sequence_id"], "raw GNSS logger_sequence_id")
    _strictly_increasing(frame["location_timestamp_ns"], "raw GNSS timestamps")
    frame["masked_from_runtime"] = _bool_series(frame["masked_from_runtime"], "masked_from_runtime")
    _validate_elapsed_clock(frame, "location_timestamp_ns", origin_ns, "raw GNSS")
    return frame


def _validate_elapsed_clock(frame: pd.DataFrame, timestamp_column: str, origin_ns: int, name: str) -> None:
    derived = (frame[timestamp_column].to_numpy(dtype=np.int64) - origin_ns) / 1e9
    elapsed = frame["elapsed_seconds"].to_numpy(dtype=float)
    if not np.all(np.isfinite(elapsed)) or np.max(np.abs(derived - elapsed), initial=0.0) > 0.005:
        raise AndroidSessionError(f"{name} elapsed_seconds disagrees with monotonic clock by more than 5 ms")


def _canonical_sensor_mapping() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for prefix, unit in (("accelerometer", "mps2"), ("gyroscope", "radps"), ("magnetometer", "ut")):
        canonical_prefix = "magnetic_field" if prefix == "magnetometer" else prefix
        for axis in "xyz":
            mapping[f"{canonical_prefix}_{axis}_{unit}"] = f"{prefix}_{axis}_{unit}"
    return mapping


def _rate_hz(times_ns: np.ndarray) -> float:
    if len(times_ns) < 2 or times_ns[-1] <= times_ns[0]:
        return 0.0
    return float((len(times_ns) - 1) * 1e9 / (times_ns[-1] - times_ns[0]))
