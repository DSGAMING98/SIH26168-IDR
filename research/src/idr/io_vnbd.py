"""Strict loader and validation utilities for synchronized IO-VNBD journeys.
The public repository stores its large CSV files with Git LFS. A normal GitHub
source archive contains small pointer files instead of sensor samples. This
module detects those pointers explicitly so a pointer can never be interpreted
as a three-row journey.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Literal

import numpy as np
import pandas as pd


class DatasetIntegrityError(RuntimeError):
    """Raised when a source is absent, truncated, or still a Git LFS pointer."""


class SchemaError(ValueError):
    """Raised when a CSV header does not match the documented IO-VNBD schema."""


SMARTPHONE_SCHEMA: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("gps_latitude_deg", "degrees", ("gps", "latitude")),
    ("gps_longitude_deg", "degrees", ("gps", "longitude")),
    ("gps_altitude_m", "m", ("gps", "altitude")),
    ("gps_speed_source", "source label: Kmh; observed values behave as m/s", ("gps", "speed")),
    ("gps_accuracy_m", "m", ("gps", "accuracy")),
    ("gps_orientation_deg", "degrees", ("gps", "orientation")),
    ("gps_satellites_in_range", "count/used", ("gps", "satellites")),
    ("time_since_start_ms", "ms", ("time", "since", "start")),
    ("timestamp_local_raw", "local datetime, timezone unspecified", ("date",)),
    ("accelerometer_x_mps2", "m/s^2", ("accelerometer", "x")),
    ("accelerometer_y_mps2", "m/s^2", ("accelerometer", "y")),
    ("accelerometer_z_mps2", "m/s^2", ("accelerometer", "z")),
    ("gravity_x_mps2", "m/s^2", ("gravity", "x")),
    ("gravity_y_mps2", "m/s^2", ("gravity", "y")),
    ("gravity_z_mps2", "m/s^2", ("gravity", "z")),
    ("gyroscope_x_radps", "rad/s", ("gyroscope", "x")),
    ("gyroscope_y_radps", "rad/s", ("gyroscope", "y")),
    ("gyroscope_z_radps", "rad/s", ("gyroscope", "z")),
    ("magnetic_field_x_ut", "microtesla", ("magnetic", "field", "x")),
    ("magnetic_field_y_ut", "microtesla", ("magnetic", "field", "y")),
    ("magnetic_field_z_ut", "microtesla", ("magnetic", "field", "z")),
    ("orientation_azimuth_deg", "degrees", ("orientation", "azimuth")),
    ("orientation_pitch_deg", "degrees", ("orientation", "pitch")),
    ("orientation_roll_deg", "degrees", ("orientation", "roll")),
)

VEHICLE_SCHEMA: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("gps_satellites", "count", ("gps", "satellites")),
    ("time_since_start_of_day_s", "s", ("time", "start", "day")),
    ("latitude_deg", "degrees", ("latitude",)),
    ("longitude_deg", "degrees", ("longitude",)),
    ("velocity_kmh", "km/h", ("velocity",)),
    ("heading_deg", "degrees", ("heading",)),
    ("height_source", "source label: km; observed values are metre-scale", ("height",)),
    ("vertical_velocity_kmh", "km/h", ("vertical", "velocity")),
    ("sample_period_s", "s", ("sample", "period")),
    ("steering_angle_deg", "degrees", ("steering", "angle")),
    ("wheel_speed_front_left_radps", "rad/s", ("wheel", "speed", "front", "left")),
    ("wheel_speed_front_right_radps", "rad/s", ("wheel", "speed", "front", "right")),
    ("wheel_speed_rear_left_radps", "rad/s", ("wheel", "speed", "rear", "left")),
    ("wheel_speed_rear_right_radps", "rad/s", ("wheel", "speed", "rear", "right")),
    ("yaw_rate_degps", "degrees/s", ("yaw", "rate")),
    ("indicated_vehicle_speed_kmh", "km/h", ("indicated", "vehicle", "speed")),
    ("longitudinal_acceleration_g", "g", ("longitudinal", "acceleration")),
    ("lateral_acceleration_g", "g", ("lateral", "acceleration")),
    ("handbrake", "binary", ("handbrake",)),
    ("gear_requested", "gear number", ("gear", "requested")),
    ("gear", "gear number", ("gear",)),
    ("engine_speed_rpm", "rev/min", ("engine", "speed")),
    ("coolant_temperature_c", "degrees Celsius", ("coolant", "temperature")),
    ("clutch_position", "binary", ("clutch", "position")),
    ("brake_pressure_psi", "psi", ("brake", "pressure")),
    ("brake_position", "binary", ("brake", "position")),
    ("battery_voltage_v", "V", ("battery", "voltage")),
    ("air_temperature_c", "degrees Celsius", ("air", "temperature")),
    ("accelerator_pedal_position", "dataset header says binary", ("accelerator", "pedal", "position")),
)


@dataclass(frozen=True)
class IOVNBDJourney:
    """A synchronized smartphone and vehicle-reference journey."""

    session_id: str
    smartphone: pd.DataFrame
    vehicle: pd.DataFrame
    smartphone_path: Path
    vehicle_path: Path
    smartphone_raw_headers: tuple[str, ...]
    vehicle_raw_headers: tuple[str, ...]


def project_root(start: Path | str | None = None) -> Path:
    """Find the nearest parent containing the IO-VNBD source directory."""

    candidate = Path(start or Path.cwd()).resolve()
    for path in (candidate, *candidate.parents):
        if (path / "IO-VNBD-master").is_dir():
            return path
    raise DatasetIntegrityError(
        f"Could not locate IO-VNBD-master from {candidate}. "
        "Run inside the project or pass project_root_path."
    )


def is_git_lfs_pointer(path: Path | str) -> bool:
    """Return True when *path* is a Git LFS pointer rather than CSV data."""

    source = Path(path)
    if not source.is_file() or source.stat().st_size > 1024:
        return False
    with source.open("rb") as stream:
        prefix = stream.read(200)
    return prefix.startswith(b"version https://git-lfs.github.com/spec/v1")


def sha256_file(path: Path | str, chunk_size: int = 1024 * 1024) -> str:
    digest = sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_session_id(session_id: str) -> str:
    value = session_id.strip()
    for prefix in ("S-", "V-"):
        if value.upper().startswith(prefix):
            value = value[len(prefix) :]
    if not value or any(char in value for char in "\\/:"):
        raise ValueError(f"Invalid IO-VNBD session id: {session_id!r}")
    return value


def _candidate_pair(root: Path, session_id: str) -> Iterable[tuple[Path, Path]]:
    sync = (
        root
        / "IO-VNBD-master"
        / "Synchronised V abd S datasets"
        / "Uncategorised IOVNB Dataset"
    )
    yield (
        sync / "S-Dataset" / f"S-{session_id}.csv",
        sync / "V-Dataset" / f"V-{session_id}.csv",
    )
    cache = root / "data" / "cache" / "io_vnbd" / session_id
    yield cache / f"S-{session_id}.csv", cache / f"V-{session_id}.csv"


def resolve_session_files(
    session_id: str,
    project_root_path: Path | str | None = None,
) -> tuple[Path, Path]:
    """Resolve a synchronized pair, preferring hydrated source files over cache."""

    session = _normalize_session_id(session_id)
    root = project_root(project_root_path)
    pointers: list[Path] = []
    for smartphone, vehicle in _candidate_pair(root, session):
        if smartphone.is_file() and vehicle.is_file():
            if is_git_lfs_pointer(smartphone) or is_git_lfs_pointer(vehicle):
                pointers.extend([smartphone, vehicle])
                continue
            return smartphone, vehicle
    if pointers:
        pointer_list = "\n".join(f"- {path}" for path in pointers)
        raise DatasetIntegrityError(
            "The requested IO-VNBD CSVs are Git LFS pointer stubs, not sensor data:\n"
            f"{pointer_list}\nHydrate the selected payloads or place verified copies under "
            f"data/cache/io_vnbd/{session}/."
        )
    raise DatasetIntegrityError(f"No synchronized smartphone/vehicle pair found for {session}.")


def _header_text(value: str) -> str:
    return " ".join(value.strip().lower().replace("-", " ").split())


def _validate_and_rename(
    frame: pd.DataFrame,
    schema: tuple[tuple[str, str, tuple[str, ...]], ...],
    source: Path,
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    raw_headers = tuple(str(column) for column in frame.columns)
    if len(raw_headers) != len(schema):
        raise SchemaError(
            f"{source} has {len(raw_headers)} columns; expected {len(schema)}."
        )
    for index, (raw, (_, _, tokens)) in enumerate(zip(raw_headers, schema, strict=True)):
        normalized = _header_text(raw)
        if not all(token in normalized for token in tokens):
            raise SchemaError(
                f"Unexpected column {index + 1} in {source}: {raw!r}; "
                f"expected tokens {tokens!r}."
            )
    renamed = frame.copy()
    renamed.columns = [field for field, _, _ in schema]
    return renamed, raw_headers


def _read_csv(path: Path, kind: Literal["smartphone", "vehicle"]) -> tuple[pd.DataFrame, tuple[str, ...]]:
    if not path.is_file():
        raise DatasetIntegrityError(f"CSV not found: {path}")
    if is_git_lfs_pointer(path):
        raise DatasetIntegrityError(f"CSV is only a Git LFS pointer: {path}")
    if path.stat().st_size < 1024:
        raise DatasetIntegrityError(f"CSV is unexpectedly small: {path}")

    # The upstream smartphone header has mixed legacy/Unicode bytes. Latin-1
    # preserves every byte deterministically; schema validation then relies on
    # semantic words rather than corrupted unit glyphs.
    frame = pd.read_csv(path, encoding="latin-1", low_memory=False)
    schema = SMARTPHONE_SCHEMA if kind == "smartphone" else VEHICLE_SCHEMA
    frame, raw_headers = _validate_and_rename(frame, schema, path)

    text_columns = {"gps_satellites_in_range", "timestamp_local_raw"}
    for column in frame.columns:
        if column not in text_columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

    if kind == "smartphone":
        # The paper and CSV label this field Kmh, but paired samples establish
        # that its numeric values are m/s (for example, 5.57 versus the VBOX
        # reference 19.969 km/h at the first row). Preserve the source value and
        # expose explicit, correctly scaled derived fields.
        frame["gps_speed_mps"] = frame["gps_speed_source"]
        frame["gps_speed_kmh"] = frame["gps_speed_source"] * 3.6
        raw_time = frame["timestamp_local_raw"].astype("string")
        normalized_time = raw_time.str.replace(r":(\d{3})$", r".\1", regex=True)
        frame["timestamp_local"] = pd.to_datetime(
            normalized_time,
            format="%Y-%m-%d %H:%M:%S.%f",
            errors="coerce",
        )
        first = frame["time_since_start_ms"].dropna()
        frame["elapsed_s"] = (
            frame["time_since_start_ms"] - (float(first.iloc[0]) if len(first) else np.nan)
        ) / 1000.0
    else:
        # The VBOX height header says km, but values of roughly 92-144 are
        # consistent with metres and with the simultaneously logged phone
        # altitude, not 92-144 km. Keep the source value and name the inferred
        # metre interpretation separately.
        frame["height_m"] = frame["height_source"]
        first = frame["time_since_start_of_day_s"].dropna()
        frame["elapsed_s"] = frame["time_since_start_of_day_s"] - (
            float(first.iloc[0]) if len(first) else np.nan
        )
    return frame, raw_headers


def load_journey(
    session_id: str = "S1",
    project_root_path: Path | str | None = None,
    smartphone_path: Path | str | None = None,
    vehicle_path: Path | str | None = None,
) -> IOVNBDJourney:
    """Load one manually synchronized IO-VNBD smartphone/vehicle pair."""

    session = _normalize_session_id(session_id)
    if (smartphone_path is None) != (vehicle_path is None):
        raise ValueError("smartphone_path and vehicle_path must be supplied together.")
    if smartphone_path is None:
        phone_source, vehicle_source = resolve_session_files(session, project_root_path)
    else:
        phone_source = Path(smartphone_path).resolve()
        vehicle_source = Path(vehicle_path).resolve()  # type: ignore[arg-type]

    smartphone, smartphone_headers = _read_csv(phone_source, "smartphone")
    vehicle, vehicle_headers = _read_csv(vehicle_source, "vehicle")
    return IOVNBDJourney(
        session_id=session,
        smartphone=smartphone,
        vehicle=vehicle,
        smartphone_path=phone_source,
        vehicle_path=vehicle_source,
        smartphone_raw_headers=smartphone_headers,
        vehicle_raw_headers=vehicle_headers,
    )


def sampling_statistics(time_s: pd.Series, gap_factor: float = 1.5) -> dict[str, Any]:
    """Calculate timestamp quality and actual sampling characteristics."""

    numeric = pd.to_numeric(time_s, errors="coerce")
    missing = int(numeric.isna().sum())
    valid = numeric.dropna().to_numpy(dtype=float)
    if valid.size < 2:
        raise ValueError("At least two valid timestamps are required.")
    delta = np.diff(valid)
    positive = delta[delta > 0]
    if positive.size == 0:
        raise ValueError("No positive timestamp intervals found.")
    median = float(np.median(positive))
    gap_threshold = median * gap_factor
    gaps = delta[delta > gap_threshold]
    missing_equivalents = int(np.maximum(np.rint(gaps / median).astype(int) - 1, 0).sum())
    return {
        "sample_count": int(len(numeric)),
        "valid_timestamp_count": int(valid.size),
        "missing_timestamp_count": missing,
        "duration_s": float(valid[-1] - valid[0]),
        "median_interval_s": median,
        "mean_interval_s": float(np.mean(positive)),
        "p95_interval_s": float(np.percentile(positive, 95)),
        "min_positive_interval_s": float(np.min(positive)),
        "max_interval_s": float(np.max(delta)),
        "approx_frequency_hz": float(1.0 / median),
        "duplicate_timestamp_count": int(np.count_nonzero(delta == 0)),
        "non_monotonic_timestamp_count": int(np.count_nonzero(delta < 0)),
        "obvious_gap_threshold_s": float(gap_threshold),
        "obvious_gap_count": int(gaps.size),
        "estimated_missing_intervals": missing_equivalents,
    }


def synchronization_statistics(journey: IOVNBDJourney) -> dict[str, Any]:
    """Validate row and elapsed-clock agreement in a synchronized pair."""

    phone = journey.smartphone["elapsed_s"].to_numpy(dtype=float)
    vehicle = journey.vehicle["elapsed_s"].to_numpy(dtype=float)
    count = min(len(phone), len(vehicle))
    residual = phone[:count] - vehicle[:count]
    finite = residual[np.isfinite(residual)]
    return {
        "smartphone_rows": int(len(phone)),
        "vehicle_rows": int(len(vehicle)),
        "equal_row_count": bool(len(phone) == len(vehicle)),
        "paired_rows": int(count),
        "elapsed_clock_residual_median_ms": float(np.median(finite) * 1000.0),
        "elapsed_clock_residual_p95_abs_ms": float(np.percentile(np.abs(finite), 95) * 1000.0),
        "elapsed_clock_residual_max_abs_ms": float(np.max(np.abs(finite)) * 1000.0),
    }


def haversine_distance_m(
    latitude_a: np.ndarray,
    longitude_a: np.ndarray,
    latitude_b: np.ndarray,
    longitude_b: np.ndarray,
) -> np.ndarray:
    """Vectorized WGS84-like spherical distance suitable for QA summaries."""

    radius_m = 6_371_008.8
    lat_a = np.radians(latitude_a)
    lat_b = np.radians(latitude_b)
    delta_lat = lat_b - lat_a
    delta_lon = np.radians(longitude_b - longitude_a)
    term = np.sin(delta_lat / 2.0) ** 2 + np.cos(lat_a) * np.cos(lat_b) * np.sin(delta_lon / 2.0) ** 2
    return 2.0 * radius_m * np.arcsin(np.sqrt(np.clip(term, 0.0, 1.0)))


def cumulative_track_distance_m(latitude: pd.Series, longitude: pd.Series) -> float:
    valid = pd.DataFrame({"lat": latitude, "lon": longitude}).dropna()
    if len(valid) < 2:
        return 0.0
    lat = valid["lat"].to_numpy(dtype=float)
    lon = valid["lon"].to_numpy(dtype=float)
    return float(haversine_distance_m(lat[:-1], lon[:-1], lat[1:], lon[1:]).sum())


def held_measurement_update_statistics(frame: pd.DataFrame) -> dict[str, Any]:
    """Measure changes in held smartphone position/speed values.

    This is an observed value-change cadence, not proof of the receiver's
    internal update rate because successive equal GNSS solutions are possible.
    """

    fields = ["gps_latitude_deg", "gps_longitude_deg", "gps_speed_kmh"]
    changed = frame[fields].ne(frame[fields].shift()).any(axis=1)
    update_times = frame.loc[changed, "elapsed_s"]
    stats = sampling_statistics(update_times.reset_index(drop=True))
    stats["held_sample_count"] = int((~changed).sum())
    stats["distinct_update_rows"] = int(changed.sum())
    return stats


def schema_units(kind: Literal["smartphone", "vehicle"]) -> dict[str, str]:
    schema = SMARTPHONE_SCHEMA if kind == "smartphone" else VEHICLE_SCHEMA
    units = {field: unit for field, unit, _ in schema}
    if kind == "smartphone":
        units.update({"gps_speed_mps": "m/s", "gps_speed_kmh": "km/h"})
    else:
        units.update({"height_m": "m"})
    return units
