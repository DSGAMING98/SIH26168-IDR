"""Versioned, runtime-safe schema for Phase 9 Android recordings."""

from __future__ import annotations

from typing import Final


SCHEMA_VERSION: Final = 2
SUPPORTED_SCHEMA_VERSIONS: Final = frozenset({1, SCHEMA_VERSION})

SENSOR_UNITS: Final = {
    "accelerometer": "m/s^2",
    "gyroscope": "rad/s",
    "magnetometer": "microtesla",
    "speed": "m/s",
    "angles": "degrees",
    "position": "WGS84 latitude/longitude degrees",
}

VECTOR_FIELDS: Final = {
    "accelerometer": tuple(f"accelerometer_{axis}_mps2" for axis in "xyz"),
    "gyroscope": tuple(f"gyroscope_{axis}_radps" for axis in "xyz"),
    "magnetometer": tuple(f"magnetometer_{axis}_ut" for axis in "xyz"),
    "gravity": tuple(f"gravity_{axis}_mps2" for axis in "xyz"),
}
ROTATION_FIELDS: Final = ("rotation_qx", "rotation_qy", "rotation_qz", "rotation_qw")
GNSS_SENSITIVE_FIELDS: Final = (
    "gnss_latitude_deg",
    "gnss_longitude_deg",
    "gnss_altitude_m",
    "gnss_speed_mps",
    "gnss_bearing_deg",
    "gnss_accuracy_m",
    "gnss_vertical_accuracy_m",
    "gnss_speed_accuracy_mps",
    "gnss_bearing_accuracy_deg",
    "gnss_provider",
)
AVAILABILITY_FIELDS: Final = (
    "accelerometer_available",
    "gyroscope_available",
    "magnetometer_available",
    "gravity_available",
    "rotation_vector_available",
    "gps_provider_available",
)
RUNTIME_COLUMNS_V1: Final = (
    "sequence_id",
    "elapsed_seconds",
    "monotonic_timestamp_ns",
    "wall_clock_utc",
    *VECTOR_FIELDS["accelerometer"],
    *VECTOR_FIELDS["gyroscope"],
    *VECTOR_FIELDS["magnetometer"],
    *VECTOR_FIELDS["gravity"],
    *ROTATION_FIELDS,
    *GNSS_SENSITIVE_FIELDS,
    "gnss_fix_age_seconds",
    "gnss_is_fresh",
    "gnss_status",
    "simulated_blackout",
    *AVAILABILITY_FIELDS,
    "ml_ood_state",
    "ml_feature_exceedance",
    "ml_correction_accepted",
)
GNSS_DIAGNOSTIC_FIELDS: Final = (
    "blackout_masks_real_fix",
    "physical_gnss_callback_count",
    "latest_physical_callback_age_seconds",
    "last_physical_gnss_timestamp_ns",
    "first_valid_gnss_fix_timestamp_ns",
    "time_to_first_fix_seconds",
    "gnss_status_available",
    "satellites_visible",
    "satellites_used_in_fix",
)
RUNTIME_COLUMNS: Final = (
    *RUNTIME_COLUMNS_V1[: RUNTIME_COLUMNS_V1.index("simulated_blackout") + 1],
    *GNSS_DIAGNOSTIC_FIELDS,
    *RUNTIME_COLUMNS_V1[RUNTIME_COLUMNS_V1.index("simulated_blackout") + 1 :],
)

RAW_IMU_COLUMNS: Final = (
    "logger_sequence_id",
    "sensor_type",
    "event_timestamp_ns",
    "elapsed_seconds",
    "wall_clock_utc",
    "x",
    "y",
    "z",
    "w",
    "accuracy",
)

RAW_GNSS_COLUMNS: Final = (
    "logger_sequence_id",
    "location_timestamp_ns",
    "elapsed_seconds",
    "wall_clock_utc",
    "latitude_deg",
    "longitude_deg",
    "altitude_m",
    "speed_mps",
    "bearing_deg",
    "accuracy_m",
    "vertical_accuracy_m",
    "speed_accuracy_mps",
    "bearing_accuracy_deg",
    "provider",
    "callback_status",
    "masked_from_runtime",
)

GNSS_STATUSES: Final = frozenset(
    {"WAITING_FOR_FIRST_FIX", "FRESH", "STALE", "INVALID", "PROVIDER_DISABLED", "SIMULATED_BLACKOUT"}
)
ML_OOD_STATES: Final = frozenset({"NOT_EVALUATED", "IN_DISTRIBUTION", "SOFT_OOD", "HARD_OOD"})
SENSOR_TYPES: Final = frozenset({"accelerometer", "gyroscope", "magnetometer", "gravity", "rotation_vector"})
