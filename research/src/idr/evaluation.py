"""Geographic and trajectory-error utilities for blackout evaluation.

IO-VNBD does not state a datum/EPSG identifier. These utilities therefore use
latitude/longitude degrees on a sphere with the IUGG mean Earth radius. The
local XY helper is an explicitly local spherical tangent approximation, not a
claim that the source coordinates belong to a particular projected CRS.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np


MEAN_EARTH_RADIUS_M = 6_371_008.8


def _matching_finite_arrays(*values: Any) -> list[np.ndarray]:
    arrays = [np.asarray(value, dtype=float) for value in values]
    shape = arrays[0].shape
    if any(array.shape != shape for array in arrays[1:]):
        raise ValueError("All coordinate arrays must have identical shapes.")
    if any(not np.all(np.isfinite(array)) for array in arrays):
        raise ValueError("Coordinates must be finite.")
    return arrays


def great_circle_distance_m(
    latitude_a_deg: Any,
    longitude_a_deg: Any,
    latitude_b_deg: Any,
    longitude_b_deg: Any,
) -> np.ndarray:
    """Return spherical great-circle distance using the haversine formula."""

    lat_a, lon_a, lat_b, lon_b = _matching_finite_arrays(
        latitude_a_deg,
        longitude_a_deg,
        latitude_b_deg,
        longitude_b_deg,
    )
    lat_a_rad = np.radians(lat_a)
    lat_b_rad = np.radians(lat_b)
    delta_lat = lat_b_rad - lat_a_rad
    delta_lon = np.radians(lon_b - lon_a)
    haversine = (
        np.sin(delta_lat / 2.0) ** 2
        + np.cos(lat_a_rad) * np.cos(lat_b_rad) * np.sin(delta_lon / 2.0) ** 2
    )
    return 2.0 * MEAN_EARTH_RADIUS_M * np.arcsin(
        np.sqrt(np.clip(haversine, 0.0, 1.0))
    )


def path_distance_m(latitude_deg: Any, longitude_deg: Any) -> float:
    """Sum great-circle distances between consecutive reference samples."""

    latitude, longitude = _matching_finite_arrays(latitude_deg, longitude_deg)
    if latitude.ndim != 1:
        raise ValueError("Path coordinates must be one-dimensional.")
    if latitude.size < 2:
        return 0.0
    segments = great_circle_distance_m(
        latitude[:-1], longitude[:-1], latitude[1:], longitude[1:]
    )
    return float(np.sum(segments))


@dataclass(frozen=True)
class LocalMetricFrame:
    """Local spherical tangent approximation metadata and coordinates."""

    x_east_m: np.ndarray
    y_north_m: np.ndarray
    origin_latitude_deg: float
    origin_longitude_deg: float
    method: str = "local spherical equirectangular approximation"


def geodetic_to_local_xy_m(
    latitude_deg: Any,
    longitude_deg: Any,
    origin_latitude_deg: float | None = None,
    origin_longitude_deg: float | None = None,
) -> LocalMetricFrame:
    """Convert a compact lat/lon track to local east/north metres.

    This equirectangular tangent approximation is appropriate for the compact
    S1 route and is intended for visualization and local error calculations.
    """

    latitude, longitude = _matching_finite_arrays(latitude_deg, longitude_deg)
    if latitude.ndim != 1 or latitude.size == 0:
        raise ValueError("At least one one-dimensional coordinate is required.")
    origin_lat = float(latitude[0] if origin_latitude_deg is None else origin_latitude_deg)
    origin_lon = float(longitude[0] if origin_longitude_deg is None else origin_longitude_deg)
    if not np.isfinite(origin_lat) or not np.isfinite(origin_lon):
        raise ValueError("Local-frame origin must be finite.")
    x_east = (
        MEAN_EARTH_RADIUS_M
        * np.cos(np.radians(origin_lat))
        * np.radians(longitude - origin_lon)
    )
    y_north = MEAN_EARTH_RADIUS_M * np.radians(latitude - origin_lat)
    return LocalMetricFrame(x_east, y_north, origin_lat, origin_lon)


def local_xy_to_geodetic(
    x_east_m: Any,
    y_north_m: Any,
    origin_latitude_deg: float,
    origin_longitude_deg: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Invert the local spherical equirectangular approximation."""

    x_east, y_north = _matching_finite_arrays(x_east_m, y_north_m)
    origin_lat = float(origin_latitude_deg)
    origin_lon = float(origin_longitude_deg)
    if not np.isfinite(origin_lat) or not np.isfinite(origin_lon):
        raise ValueError("Local-frame origin must be finite.")
    longitude_scale = MEAN_EARTH_RADIUS_M * np.cos(np.radians(origin_lat))
    if abs(longitude_scale) < 1e-12:
        raise ValueError("Local east coordinate is undefined at the poles.")
    latitude = origin_lat + np.degrees(y_north / MEAN_EARTH_RADIUS_M)
    longitude = origin_lon + np.degrees(x_east / longitude_scale)
    return latitude, longitude


def position_error_series_m(
    predicted_latitude_deg: Any,
    predicted_longitude_deg: Any,
    reference_latitude_deg: Any,
    reference_longitude_deg: Any,
) -> np.ndarray:
    """Return sample-wise horizontal great-circle error in metres."""

    return great_circle_distance_m(
        predicted_latitude_deg,
        predicted_longitude_deg,
        reference_latitude_deg,
        reference_longitude_deg,
    )


def drift_percentage(
    final_position_error_m: float,
    reference_distance_m: float,
) -> float | None:
    """Return final error / reference distance * 100, or None at zero distance."""

    if not np.isfinite(final_position_error_m) or not np.isfinite(reference_distance_m):
        raise ValueError("Error and reference distance must be finite.")
    if final_position_error_m < 0 or reference_distance_m < 0:
        raise ValueError("Error and reference distance cannot be negative.")
    if reference_distance_m == 0:
        return None
    return float(final_position_error_m / reference_distance_m * 100.0)


@dataclass(frozen=True)
class PositionErrorMetrics:
    sample_count: int
    final_position_error_m: float
    mean_position_error_m: float
    rmse_position_error_m: float
    maximum_position_error_m: float
    p95_position_error_m: float
    reference_distance_m: float
    drift_percentage: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def summarize_position_errors(
    errors_m: Any,
    reference_distance_m: float,
) -> PositionErrorMetrics:
    """Calculate the Phase 3 metric set from a real prediction error series.

    Phase 2 defines and tests this utility but does not call it with model output.
    """

    errors = np.asarray(errors_m, dtype=float)
    if errors.ndim != 1 or errors.size == 0:
        raise ValueError("At least one one-dimensional position error is required.")
    if not np.all(np.isfinite(errors)) or np.any(errors < 0):
        raise ValueError("Position errors must be finite and non-negative.")
    if reference_distance_m < 0 or not np.isfinite(reference_distance_m):
        raise ValueError("Reference distance must be finite and non-negative.")
    final_error = float(errors[-1])
    return PositionErrorMetrics(
        sample_count=int(errors.size),
        final_position_error_m=final_error,
        mean_position_error_m=float(np.mean(errors)),
        rmse_position_error_m=float(np.sqrt(np.mean(np.square(errors)))),
        maximum_position_error_m=float(np.max(errors)),
        p95_position_error_m=float(np.percentile(errors, 95)),
        reference_distance_m=float(reference_distance_m),
        drift_percentage=drift_percentage(final_error, float(reference_distance_m)),
    )
