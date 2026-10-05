"""Version 1 telemetry allowlist; only completed estimator snapshots cross this boundary.

All unavailable scalar measurements are null. No physical GNSS coordinates, raw
sensor frames, reference trajectories, credentials or arbitrary extension fields
are accepted. Nanosecond timestamps are decimal strings to preserve JS precision.
"""
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


Label = Annotated[str, Field(max_length=64, pattern=r"^[A-Z][A-Z0-9_ -]*$")]
Nonnegative = Annotated[float, Field(ge=0, le=1e9)]
Rate = Annotated[float, Field(ge=0, le=10000)]
Count = Annotated[int, Field(ge=0, le=1000000000)]


class EstimatedPosition(StrictModel):
    latitude: Annotated[float, Field(ge=-90, le=90)] | None = None
    longitude: Annotated[float, Field(ge=-180, le=180)] | None = None
    local_east_m: Annotated[float, Field(ge=-1e8, le=1e8)] | None = None
    local_north_m: Annotated[float, Field(ge=-1e8, le=1e8)] | None = None

    @model_validator(mode="after")
    def paired_coordinates(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be available together")
        if (self.local_east_m is None) != (self.local_north_m is None):
            raise ValueError("local coordinates must be available together")
        return self


class Motion(StrictModel):
    speed_mps: Annotated[float, Field(ge=0, le=1000)] | None = None
    speed_kmh: Annotated[float, Field(ge=0, le=3600)] | None = None
    heading_deg: Annotated[float, Field(ge=0, lt=360)] | None = None


class Navigation(StrictModel):
    localization_state: Literal["WAITING_FOR_GNSS", "CALIBRATING", "CALIBRATION_REQUIRED", "GNSS_ACTIVE", "GNSS_DEGRADED", "IDR_ACTIVE", "GNSS_VERIFYING", "GNSS_RECOVERING", "ERROR"]
    gnss_state: Label | None = None
    dr_duration_s: Nonnegative | None = None
    uncertainty_m: Nonnegative | None = None
    confidence: Label | None = None
    alignment_state: Label | None = None
    motion_state: Label | None = None


class Ai(StrictModel):
    state: Literal["WARMING", "ASSISTED", "SAFETY_FALLBACK", "UNAVAILABLE"]
    ml_state: Label | None = None
    ood_exceedance: Nonnegative | None = None


class Sensors(StrictModel):
    accelerometer_hz: Rate | None = None
    gyroscope_hz: Rate | None = None
    magnetometer_hz: Rate | None = None
    runtime_hz: Rate | None = None


class GnssObservability(StrictModel):
    satellites_visible: Annotated[int, Field(ge=0, le=1000)] | None = None
    satellites_used: Annotated[int, Field(ge=0, le=1000)] | None = None
    status_available: bool | None = None
    physical_callback_count: Count | None = None
    latest_callback_age_s: Nonnegative | None = None
    blackout_masks_real_fix: bool | None = None


class Engine(StrictModel):
    avg_ms: Nonnegative | None = None
    p95_ms: Nonnegative | None = None


class Device(StrictModel):
    battery_percent: Annotated[int, Field(ge=0, le=100)] | None = None
    battery_temperature_c: Annotated[float, Field(ge=-100, le=200)] | None = None
    thermal_state: Label | None = None


class Telemetry(StrictModel):
    schema_version: Literal[1]
    session_id: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]
    sequence: Annotated[int, Field(ge=0, le=9007199254740991)]
    timestamp_ns: Annotated[str, Field(min_length=1, max_length=19, pattern=r"^(0|[1-9][0-9]*)$")]
    wall_time_utc: Annotated[str, Field(max_length=40, pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?Z$")] | None = None
    mode: Literal["LIVE", "DEMO"]
    estimated_position: EstimatedPosition
    motion: Motion
    navigation: Navigation
    ai: Ai
    sensors: Sensors
    gnss_observability: GnssObservability
    engine: Engine
    device: Device
    field_test_state: Label | None = None
    map_mode: Label | None = None
    recording: bool

    @field_validator("schema_version", mode="before")
    @classmethod
    def exact_integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("schema_version must be integer 1")
        return value

    @field_validator("wall_time_utc")
    @classmethod
    def valid_utc_calendar_time(cls, value):
        if value is not None:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value
