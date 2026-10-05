"""Causal adapter for locally available Google Smartphone Decimeter 2022 data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ...evaluation import great_circle_distance_m
from ..canonical import CanonicalEvaluationReference, CanonicalRuntimeSession


WGS84_A_M = 6_378_137.0
WGS84_E2 = 6.69437999014e-3


def ecef_to_wgs84(x_m: np.ndarray, y_m: np.ndarray, z_m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Convert WLS ECEF coordinates to WGS84 geodetic latitude/longitude."""

    x = np.asarray(x_m, dtype=float)
    y = np.asarray(y_m, dtype=float)
    z = np.asarray(z_m, dtype=float)
    longitude = np.arctan2(y, x)
    p = np.hypot(x, y)
    latitude = np.arctan2(z, p * (1.0 - WGS84_E2))
    for _ in range(7):
        sin_latitude = np.sin(latitude)
        radius = WGS84_A_M / np.sqrt(1.0 - WGS84_E2 * sin_latitude * sin_latitude)
        latitude = np.arctan2(z + WGS84_E2 * radius * sin_latitude, p)
    return np.degrees(latitude), (np.degrees(longitude) + 180.0) % 360.0 - 180.0


def _course_speed(latitude: np.ndarray, longitude: np.ndarray, elapsed: np.ndarray, horizon_s: float) -> tuple[np.ndarray, np.ndarray]:
    speed = np.zeros(len(elapsed), dtype=float)
    course = np.zeros(len(elapsed), dtype=float)
    for index in range(1, len(elapsed)):
        target = elapsed[index] - horizon_s
        previous = int(np.searchsorted(elapsed, target, side="right") - 1)
        previous = min(index - 1, max(0, previous))
        dt = elapsed[index] - elapsed[previous]
        speed[index] = float(great_circle_distance_m(latitude[previous], longitude[previous], latitude[index], longitude[index])) / dt
        lat1 = np.radians(latitude[previous])
        lat2 = np.radians(latitude[index])
        dlon = np.radians(longitude[index] - longitude[previous])
        east = np.sin(dlon) * np.cos(lat2)
        north = np.cos(lat1) * np.sin(lat2) - np.sin(lat1) * np.cos(lat2) * np.cos(dlon)
        course[index] = float(np.degrees(np.arctan2(east, north)) % 360.0)
    if len(speed) > 1:
        speed[0] = speed[1]
        course[0] = course[1]
    return speed, course


def _read_sensor(path: Path, message_type: str, origin_ms: int, bin_ms: int) -> pd.DataFrame:
    chunks: list[pd.DataFrame] = []
    columns = ["MessageType", "utcTimeMillis", "MeasurementX", "MeasurementY", "MeasurementZ", "BiasX", "BiasY", "BiasZ"]
    for chunk in pd.read_csv(path, usecols=columns, chunksize=250_000):
        selected = chunk.loc[chunk["MessageType"].eq(message_type)].copy()
        if not selected.empty:
            chunks.append(selected)
    if not chunks:
        raise ValueError(f"No {message_type} rows in {path}")
    data = pd.concat(chunks, ignore_index=True)
    measurement = data[["MeasurementX", "MeasurementY", "MeasurementZ"]].to_numpy(dtype=float)
    bias = data[["BiasX", "BiasY", "BiasZ"]].fillna(0.0).to_numpy(dtype=float)
    calibrated = measurement - bias
    # Strictly causal right-closed bins: every contributing timestamp is <= bin end.
    bin_index = np.ceil((data["utcTimeMillis"].to_numpy(dtype=np.int64) - origin_ms) / bin_ms).astype(np.int64)
    frame = pd.DataFrame({"bin": bin_index, "x": calibrated[:, 0], "y": calibrated[:, 1], "z": calibrated[:, 2]})
    return frame.groupby("bin", sort=True, as_index=False)[["x", "y", "z"]].mean()


@dataclass(frozen=True)
class SmartphoneDecimeterAdapter:
    session_path: Path
    session_id: str
    effective_rate_hz: float = 10.0
    gnss_motion_horizon_s: float = 5.0

    def _origin_ms(self) -> int:
        first = pd.read_csv(self.session_path / "device_gnss.csv", usecols=["utcTimeMillis"], nrows=1)
        return int(first["utcTimeMillis"].iloc[0])

    def load_runtime(self) -> CanonicalRuntimeSession:
        """Load runtime phone streams only; this method never reads ground_truth.csv."""

        origin_ms = self._origin_ms()
        bin_ms = int(round(1000.0 / self.effective_rate_hz))
        imu_path = self.session_path / "device_imu.csv"
        streams = {
            "accelerometer": _read_sensor(imu_path, "UncalAccel", origin_ms, bin_ms),
            "gyroscope": _read_sensor(imu_path, "UncalGyro", origin_ms, bin_ms),
            "magnetic_field": _read_sensor(imu_path, "UncalMag", origin_ms, bin_ms),
        }
        sensor: pd.DataFrame | None = None
        for prefix, frame in streams.items():
            renamed = frame.rename(columns={axis: f"{prefix}_{axis}" for axis in "xyz"})
            sensor = renamed if sensor is None else sensor.merge(renamed, on="bin", how="inner", validate="one_to_one")
        assert sensor is not None
        sensor["elapsed_s"] = sensor["bin"].to_numpy(dtype=float) / self.effective_rate_hz
        sensor["timestamp_utc_ms"] = origin_ms + sensor["bin"].to_numpy(dtype=np.int64) * bin_ms
        sensor = sensor.rename(
            columns={
                **{f"accelerometer_{a}": f"accelerometer_{a}_mps2" for a in "xyz"},
                **{f"gyroscope_{a}": f"gyroscope_{a}_radps" for a in "xyz"},
                **{f"magnetic_field_{a}": f"magnetic_field_{a}_ut" for a in "xyz"},
            }
        )

        raw = pd.read_csv(
            self.session_path / "device_gnss.csv",
            usecols=["utcTimeMillis", "WlsPositionXEcefMeters", "WlsPositionYEcefMeters", "WlsPositionZEcefMeters"],
        ).drop_duplicates("utcTimeMillis", keep="first").sort_values("utcTimeMillis")
        raw = raw.dropna().reset_index(drop=True)
        latitude, longitude = ecef_to_wgs84(
            raw["WlsPositionXEcefMeters"].to_numpy(dtype=float),
            raw["WlsPositionYEcefMeters"].to_numpy(dtype=float),
            raw["WlsPositionZEcefMeters"].to_numpy(dtype=float),
        )
        elapsed = (raw["utcTimeMillis"].to_numpy(dtype=float) - origin_ms) / 1000.0
        speed, course = _course_speed(latitude, longitude, elapsed, self.gnss_motion_horizon_s)
        gnss = pd.DataFrame(
            {
                "elapsed_s": elapsed,
                "timestamp_utc_ms": raw["utcTimeMillis"].to_numpy(dtype=np.int64),
                "gps_latitude_deg": latitude,
                "gps_longitude_deg": longitude,
                "gps_speed_mps": speed,
                "gps_orientation_deg": course,
            }
        )
        return CanonicalRuntimeSession(
            sensor.drop(columns="bin"),
            gnss,
            {
                "dataset": "Google Smartphone Decimeter 2022",
                "session_id": self.session_id,
                "session_path": str(self.session_path),
                "effective_rate_hz": self.effective_rate_hz,
                "resampling": "right-closed trailing-bin arithmetic mean",
                "gnss_source": "runtime WLS ECEF; causal 5-second backward speed/course",
            },
        )

    def load_reference(self) -> CanonicalEvaluationReference:
        """Load hidden labels separately; callers invoke only after prediction."""

        origin_ms = self._origin_ms()
        data = pd.read_csv(
            self.session_path / "ground_truth.csv",
            usecols=["UnixTimeMillis", "LatitudeDegrees", "LongitudeDegrees", "SpeedMps", "BearingDegrees"],
        ).drop_duplicates("UnixTimeMillis", keep="first").sort_values("UnixTimeMillis")
        reference = pd.DataFrame(
            {
                "elapsed_s": (data["UnixTimeMillis"].to_numpy(dtype=float) - origin_ms) / 1000.0,
                "timestamp_utc_ms": data["UnixTimeMillis"].to_numpy(dtype=np.int64),
                "latitude_deg": data["LatitudeDegrees"].to_numpy(dtype=float),
                "longitude_deg": data["LongitudeDegrees"].to_numpy(dtype=float),
                "speed_mps": data["SpeedMps"].to_numpy(dtype=float),
                "bearing_deg": data["BearingDegrees"].to_numpy(dtype=float),
            }
        )
        return CanonicalEvaluationReference(
            reference,
            {"dataset": "Google Smartphone Decimeter 2022", "session_id": self.session_id, "visibility": "evaluation only"},
        )
