"""Multi-rate edge IDR runtime for external IMUs.

The Android application remains the primary product.  This module supplies the second deployment
surface required by SIH26168: a deterministic software engine that accepts calibrated external IMU
samples at their native rate (including 200 Hz FOG streams), propagates a planar vehicle state at
that rate, and accepts slower GNSS, ML-speed and road-constraint updates without down-sampling the
propagation loop.

Coordinates are a caller-owned local tangent plane: +X east, +Y north, yaw clockwise from north.
The state intentionally has no lateral velocity.  That is the non-holonomic constraint: distance is
propagated only along the vehicle heading, so the estimator cannot slide sideways or move vertically.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import atan2, cos, hypot, isfinite, pi, sin, sqrt
from typing import Callable, Iterable, Sequence


@dataclass(frozen=True)
class ExternalImuSample:
    timestamp_s: float
    acceleration_mps2: tuple[float, float, float]
    angular_rate_radps: tuple[float, float, float]
    stationary_hint: bool = False


@dataclass(frozen=True)
class ExternalGnssFix:
    timestamp_s: float
    east_m: float
    north_m: float
    speed_mps: float | None = None
    course_rad: float | None = None
    horizontal_accuracy_m: float = 5.0


@dataclass(frozen=True)
class RoadSegment:
    start_east_m: float
    start_north_m: float
    end_east_m: float
    end_north_m: float


@dataclass(frozen=True)
class EdgeIdrConfig:
    # Rows convert sensor axes to vehicle forward/left/up axes.  This makes the engine independent
    # of a specific phone or FOG mounting convention.
    sensor_to_vehicle: tuple[tuple[float, float, float], ...] = (
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    )
    maximum_speed_mps: float = 70.0
    maximum_acceleration_mps2: float = 12.0
    maximum_yaw_rate_radps: float = 2.5
    transient_acceleration_limit_mps2: float = 4.0
    transient_yaw_rate_limit_radps: float = 0.65
    stationary_acceleration_mps2: float = 0.22
    stationary_yaw_rate_radps: float = 0.025
    stationary_confirmation_s: float = 1.0
    bias_learning_rate: float = 0.02
    gnss_position_gain: float = 0.35
    gnss_speed_gain: float = 0.45
    gnss_course_gain: float = 0.25
    ml_update_hz: float = 10.0
    ml_window_s: float = 2.0

    def __post_init__(self) -> None:
        matrix = self.sensor_to_vehicle
        if len(matrix) != 3 or any(len(row) != 3 for row in matrix):
            raise ValueError("sensor_to_vehicle must be a 3x3 matrix")
        values = [value for row in matrix for value in row]
        if not all(isfinite(value) for value in values):
            raise ValueError("sensor_to_vehicle must be finite")
        if self.maximum_speed_mps <= 0 or self.ml_update_hz <= 0 or self.ml_window_s <= 0:
            raise ValueError("rate, speed and window settings must be positive")


@dataclass(frozen=True)
class EdgeNavigationState:
    timestamp_s: float
    east_m: float
    north_m: float
    speed_mps: float
    yaw_rad: float
    acceleration_bias_mps2: float
    gyro_bias_radps: float
    stationary: bool
    update_rate_hz: float
    samples_processed: int
    ml_updates: int
    map_updates: int


MlSpeedCorrection = Callable[[Sequence[tuple[float, float, float, float]]], float | None]


class _RobustScalar:
    def __init__(self, minimum_limit: float, window_size: int = 9) -> None:
        self.minimum_limit = minimum_limit
        self.values: deque[float] = deque(maxlen=window_size)

    def update(self, value: float) -> float:
        if len(self.values) < 3:
            self.values.append(value)
            return value
        ordered = sorted(self.values)
        median = ordered[len(ordered) // 2]
        deviations = sorted(abs(item - median) for item in self.values)
        mad = deviations[len(deviations) // 2]
        limit = max(self.minimum_limit, 6.0 * 1.4826 * mad)
        guarded = min(median + limit, max(median - limit, value))
        self.values.append(value)
        return guarded


class StreamingRoadMatcher:
    """Bounded nearest-segment constraint for a preloaded offline road graph."""

    def __init__(
        self,
        segments: Iterable[RoadSegment],
        *,
        search_radius_m: float = 35.0,
        maximum_correction_m: float = 3.0,
        gain: float = 0.25,
    ) -> None:
        self.segments = tuple(segments)
        if not self.segments:
            raise ValueError("At least one road segment is required")
        if search_radius_m <= 0 or maximum_correction_m <= 0 or not 0 < gain <= 1:
            raise ValueError("Road-matching limits must be positive and gain must be in (0, 1]")
        self.search_radius_m = search_radius_m
        self.maximum_correction_m = maximum_correction_m
        self.gain = gain

    def constrain(self, east_m: float, north_m: float, yaw_rad: float) -> tuple[float, float] | None:
        best: tuple[float, float, float] | None = None
        for segment in self.segments:
            projected = self._project(east_m, north_m, segment)
            distance = hypot(projected[0] - east_m, projected[1] - north_m)
            if distance > self.search_radius_m:
                continue
            segment_yaw = atan2(
                segment.end_east_m - segment.start_east_m,
                segment.end_north_m - segment.start_north_m,
            )
            heading_error = abs(_wrap(segment_yaw - yaw_rad))
            # Direction is ambiguous for two-way roads, so compare the reverse direction too.
            heading_error = min(heading_error, abs(_wrap(segment_yaw + pi - yaw_rad)))
            score = distance + 8.0 * heading_error
            if best is None or score < best[2]:
                best = (projected[0], projected[1], score)
        if best is None:
            return None
        delta_e = best[0] - east_m
        delta_n = best[1] - north_m
        distance = hypot(delta_e, delta_n)
        if distance <= 1e-12:
            return east_m, north_m
        correction = min(self.maximum_correction_m, distance * self.gain)
        return east_m + delta_e / distance * correction, north_m + delta_n / distance * correction

    @staticmethod
    def _project(east_m: float, north_m: float, segment: RoadSegment) -> tuple[float, float]:
        dx = segment.end_east_m - segment.start_east_m
        dy = segment.end_north_m - segment.start_north_m
        denominator = dx * dx + dy * dy
        if denominator <= 1e-12:
            return segment.start_east_m, segment.start_north_m
        amount = ((east_m - segment.start_east_m) * dx + (north_m - segment.start_north_m) * dy) / denominator
        amount = min(1.0, max(0.0, amount))
        return segment.start_east_m + amount * dx, segment.start_north_m + amount * dy


class EdgeIdrEngine:
    """Causal high-rate vehicle IDR with optional ML and offline road constraints."""

    def __init__(
        self,
        config: EdgeIdrConfig = EdgeIdrConfig(),
        *,
        ml_speed_correction: MlSpeedCorrection | None = None,
        road_matcher: StreamingRoadMatcher | None = None,
    ) -> None:
        self.config = config
        self.ml_speed_correction = ml_speed_correction
        self.road_matcher = road_matcher
        self._last_timestamp_s: float | None = None
        self._first_timestamp_s: float | None = None
        self._east_m = 0.0
        self._north_m = 0.0
        self._speed_mps = 0.0
        self._yaw_rad = 0.0
        self._acceleration_bias_mps2 = 0.0
        self._gyro_bias_radps = 0.0
        self._stationary_s = 0.0
        self._stationary = False
        self._samples_processed = 0
        self._ml_updates = 0
        self._map_updates = 0
        self._last_ml_timestamp_s: float | None = None
        self._feature_window: deque[tuple[float, float, float, float]] = deque()
        self._forward_filter = _RobustScalar(config.transient_acceleration_limit_mps2)
        self._left_filter = _RobustScalar(config.transient_acceleration_limit_mps2)
        self._yaw_filter = _RobustScalar(config.transient_yaw_rate_limit_radps)

    def ingest_imu(self, sample: ExternalImuSample) -> EdgeNavigationState:
        self._validate_sample(sample)
        if self._last_timestamp_s is None:
            self._last_timestamp_s = sample.timestamp_s
            self._first_timestamp_s = sample.timestamp_s
            self._samples_processed = 1
            return self.state()
        dt_s = sample.timestamp_s - self._last_timestamp_s
        if dt_s <= 0:
            raise ValueError("IMU timestamps must be strictly increasing")
        if dt_s > 0.25:
            raise ValueError("IMU stream gap exceeds 250 ms")
        self._last_timestamp_s = sample.timestamp_s

        acceleration = self._transform(sample.acceleration_mps2)
        angular_rate = self._transform(sample.angular_rate_radps)
        forward = self._forward_filter.update(
            max(-self.config.maximum_acceleration_mps2, min(self.config.maximum_acceleration_mps2, acceleration[0]))
        )
        left = self._left_filter.update(
            max(-self.config.maximum_acceleration_mps2, min(self.config.maximum_acceleration_mps2, acceleration[1]))
        )
        yaw_rate = self._yaw_filter.update(
            max(-self.config.maximum_yaw_rate_radps, min(self.config.maximum_yaw_rate_radps, angular_rate[2]))
        )

        quiet = sample.stationary_hint or (
            hypot(forward, left) <= self.config.stationary_acceleration_mps2
            and abs(yaw_rate) <= self.config.stationary_yaw_rate_radps
        )
        self._stationary_s = self._stationary_s + dt_s if quiet else 0.0
        self._stationary = self._stationary_s >= self.config.stationary_confirmation_s
        if self._stationary:
            rate = self.config.bias_learning_rate
            self._acceleration_bias_mps2 += rate * (forward - self._acceleration_bias_mps2)
            self._gyro_bias_radps += rate * (yaw_rate - self._gyro_bias_radps)

        corrected_forward = forward - self._acceleration_bias_mps2
        corrected_yaw_rate = yaw_rate - self._gyro_bias_radps
        old_speed = self._speed_mps
        self._yaw_rad = _wrap(self._yaw_rad + corrected_yaw_rate * dt_s)
        if self._stationary:
            self._speed_mps = 0.0
        else:
            self._speed_mps = min(
                self.config.maximum_speed_mps,
                max(0.0, self._speed_mps + corrected_forward * dt_s),
            )
        average_speed = 0.5 * (old_speed + self._speed_mps)
        # Non-holonomic propagation: no lateral or vertical displacement state exists.
        self._east_m += average_speed * sin(self._yaw_rad) * dt_s
        self._north_m += average_speed * cos(self._yaw_rad) * dt_s

        self._feature_window.append((forward, left, yaw_rate, self._speed_mps))
        maximum_samples = max(4, int(self.config.ml_window_s / max(dt_s, 1e-4)) + 2)
        while len(self._feature_window) > maximum_samples:
            self._feature_window.popleft()
        if len(self._feature_window) >= maximum_samples - 2:
            self._apply_ml(sample.timestamp_s)
        self._apply_map_constraint()
        self._samples_processed += 1
        return self.state()

    def ingest_gnss(self, fix: ExternalGnssFix) -> EdgeNavigationState:
        values = (fix.timestamp_s, fix.east_m, fix.north_m, fix.horizontal_accuracy_m)
        if not all(isfinite(value) for value in values) or fix.horizontal_accuracy_m <= 0:
            raise ValueError("GNSS fix is invalid")
        if self._last_timestamp_s is not None and fix.timestamp_s < self._last_timestamp_s - 1.0:
            raise ValueError("GNSS fix is stale")
        gain_scale = min(1.0, max(0.1, 5.0 / fix.horizontal_accuracy_m))
        position_gain = self.config.gnss_position_gain * gain_scale
        self._east_m += position_gain * (fix.east_m - self._east_m)
        self._north_m += position_gain * (fix.north_m - self._north_m)
        if fix.speed_mps is not None:
            if not isfinite(fix.speed_mps) or fix.speed_mps < 0:
                raise ValueError("GNSS speed is invalid")
            self._speed_mps += self.config.gnss_speed_gain * (fix.speed_mps - self._speed_mps)
        if fix.course_rad is not None:
            if not isfinite(fix.course_rad):
                raise ValueError("GNSS course is invalid")
            self._yaw_rad = _wrap(self._yaw_rad + self.config.gnss_course_gain * _wrap(fix.course_rad - self._yaw_rad))
        return self.state()

    def state(self) -> EdgeNavigationState:
        timestamp = self._last_timestamp_s if self._last_timestamp_s is not None else 0.0
        elapsed = timestamp - self._first_timestamp_s if self._first_timestamp_s is not None else 0.0
        rate = (self._samples_processed - 1) / elapsed if elapsed > 0 and self._samples_processed > 1 else 0.0
        return EdgeNavigationState(
            timestamp_s=timestamp,
            east_m=self._east_m,
            north_m=self._north_m,
            speed_mps=self._speed_mps,
            yaw_rad=self._yaw_rad,
            acceleration_bias_mps2=self._acceleration_bias_mps2,
            gyro_bias_radps=self._gyro_bias_radps,
            stationary=self._stationary,
            update_rate_hz=rate,
            samples_processed=self._samples_processed,
            ml_updates=self._ml_updates,
            map_updates=self._map_updates,
        )

    def _apply_ml(self, timestamp_s: float) -> None:
        if self.ml_speed_correction is None:
            return
        interval = 1.0 / self.config.ml_update_hz
        if self._last_ml_timestamp_s is not None and timestamp_s - self._last_ml_timestamp_s < interval:
            return
        correction = self.ml_speed_correction(tuple(self._feature_window))
        self._last_ml_timestamp_s = timestamp_s
        if correction is None:
            return
        if not isfinite(correction):
            raise ValueError("ML speed correction must be finite")
        self._speed_mps = min(self.config.maximum_speed_mps, max(0.0, self._speed_mps + max(-3.0, min(3.0, correction))))
        self._ml_updates += 1

    def _apply_map_constraint(self) -> None:
        if self.road_matcher is None:
            return
        matched = self.road_matcher.constrain(self._east_m, self._north_m, self._yaw_rad)
        if matched is not None:
            self._east_m, self._north_m = matched
            self._map_updates += 1

    def _transform(self, vector: tuple[float, float, float]) -> tuple[float, float, float]:
        return tuple(sum(row[index] * vector[index] for index in range(3)) for row in self.config.sensor_to_vehicle)  # type: ignore[return-value]

    @staticmethod
    def _validate_sample(sample: ExternalImuSample) -> None:
        values = (sample.timestamp_s, *sample.acceleration_mps2, *sample.angular_rate_radps)
        if not all(isfinite(value) for value in values):
            raise ValueError("IMU sample must be finite")


def _wrap(value: float) -> float:
    return (value + pi) % (2.0 * pi) - pi
