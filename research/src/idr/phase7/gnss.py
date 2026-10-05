"""Causal GNSS observation validation and genuine-fix freshness tracking."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np

from ..evaluation import great_circle_distance_m
from .config import Phase7Config


class GNSSClassification(str, Enum):
    FRESH = "FRESH"
    REPEATED = "REPEATED"
    INVALID = "INVALID"
    NO_GNSS = "NO_GNSS"


@dataclass(frozen=True)
class GNSSObservation:
    elapsed_s: float
    latitude_deg: float | None
    longitude_deg: float | None
    altitude_m: float | None
    speed_mps: float | None
    course_deg: float | None
    accuracy_m: float | None
    satellites_in_range: str | None = None

    @classmethod
    def from_mapping(cls, row: Any) -> "GNSSObservation":
        def value(name: str) -> Any:
            item = row[name]
            return None if item is None or (isinstance(item, (float, np.floating)) and not np.isfinite(item)) else item

        return cls(
            elapsed_s=float(row["elapsed_s"]),
            latitude_deg=value("gps_latitude_deg"),
            longitude_deg=value("gps_longitude_deg"),
            altitude_m=value("gps_altitude_m"),
            speed_mps=value("gps_speed_mps"),
            course_deg=value("gps_orientation_deg"),
            accuracy_m=value("gps_accuracy_m"),
            satellites_in_range=value("gps_satellites_in_range"),
        )

    @classmethod
    def missing(cls, elapsed_s: float) -> "GNSSObservation":
        return cls(float(elapsed_s), None, None, None, None, None, None, None)


@dataclass(frozen=True)
class GNSSFreshnessResult:
    classification: GNSSClassification
    reason: str
    time_since_last_fresh_s: float
    position_change_m: float | None
    speed_change_mps: float | None
    course_change_deg: float | None
    altitude_change_m: float | None


def circular_difference_deg(first: float, second: float) -> float:
    return float((float(first) - float(second) + 180.0) % 360.0 - 180.0)


def initial_bearing_deg(first: GNSSObservation, second: GNSSObservation) -> float:
    if first.latitude_deg is None or first.longitude_deg is None or second.latitude_deg is None or second.longitude_deg is None:
        raise ValueError("Bearing requires two valid GNSS positions.")
    lat1, lat2 = np.radians([first.latitude_deg, second.latitude_deg])
    delta_lon = math.radians(second.longitude_deg - first.longitude_deg)
    east = math.sin(delta_lon) * math.cos(lat2)
    north = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon)
    return float(math.degrees(math.atan2(east, north)) % 360.0)


class GNSSFreshnessTracker:
    """Classify one current observation without looking ahead."""

    def __init__(self, config: Phase7Config):
        self.config = config
        self.last_fresh: GNSSObservation | None = None

    def _validity_reason(self, observation: GNSSObservation) -> str | None:
        required = (
            observation.latitude_deg,
            observation.longitude_deg,
            observation.altitude_m,
            observation.speed_mps,
            observation.course_deg,
            observation.accuracy_m,
        )
        if all(value is None for value in required):
            return "no_gnss_fields"
        if any(value is None for value in required):
            return "partial_or_nonfinite_gnss"
        assert observation.latitude_deg is not None and observation.longitude_deg is not None
        assert observation.speed_mps is not None and observation.course_deg is not None
        assert observation.accuracy_m is not None
        if not (-90 <= observation.latitude_deg <= 90 and -180 <= observation.longitude_deg <= 180):
            return "coordinate_out_of_range"
        if observation.speed_mps < 0 or observation.speed_mps > self.config.maximum_reported_speed_mps:
            return "reported_speed_implausible"
        if not (0 <= observation.course_deg < 360):
            return "course_out_of_range"
        if observation.accuracy_m <= 0 or observation.accuracy_m > self.config.maximum_gnss_accuracy_m:
            return "accuracy_invalid_or_excessive"
        return None

    def classify(self, observation: GNSSObservation) -> GNSSFreshnessResult:
        validity = self._validity_reason(observation)
        age = math.inf if self.last_fresh is None else observation.elapsed_s - self.last_fresh.elapsed_s
        if validity == "no_gnss_fields":
            return GNSSFreshnessResult(GNSSClassification.NO_GNSS, validity, age, None, None, None, None)
        if validity is not None:
            return GNSSFreshnessResult(GNSSClassification.INVALID, validity, age, None, None, None, None)
        if self.last_fresh is None:
            self.last_fresh = observation
            return GNSSFreshnessResult(GNSSClassification.FRESH, "first_valid_solution", 0.0, None, None, None, None)
        if observation.elapsed_s <= self.last_fresh.elapsed_s:
            return GNSSFreshnessResult(GNSSClassification.INVALID, "non_monotonic_gnss_time", age, None, None, None, None)
        previous = self.last_fresh
        assert observation.latitude_deg is not None and observation.longitude_deg is not None
        assert previous.latitude_deg is not None and previous.longitude_deg is not None
        position_change = float(great_circle_distance_m(previous.latitude_deg, previous.longitude_deg, observation.latitude_deg, observation.longitude_deg))
        speed_change = abs(float(observation.speed_mps) - float(previous.speed_mps))
        course_change = abs(circular_difference_deg(float(observation.course_deg), float(previous.course_deg)))
        altitude_change = abs(float(observation.altitude_m) - float(previous.altitude_m))
        changed = (
            position_change > self.config.position_change_tolerance_m
            or speed_change > self.config.speed_change_tolerance_mps
            or course_change > self.config.course_change_tolerance_deg
            or altitude_change > self.config.altitude_change_tolerance_m
        )
        if changed:
            self.last_fresh = observation
            return GNSSFreshnessResult(
                GNSSClassification.FRESH,
                "navigation_solution_changed",
                0.0,
                position_change,
                speed_change,
                course_change,
                altitude_change,
            )
        return GNSSFreshnessResult(
            GNSSClassification.REPEATED,
            "stored_solution_within_tolerance",
            age,
            position_change,
            speed_change,
            course_change,
            altitude_change,
        )
