"""Conservative causal low-dynamics and stationary classification."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum

import numpy as np


class MotionState(str, Enum):
    MOVING = "MOVING"
    LOW_DYNAMICS = "LOW_DYNAMICS"
    LIKELY_STATIONARY = "LIKELY_STATIONARY"


@dataclass(frozen=True)
class MotionStateSettings:
    window_s: float
    enter_accel_rms_mps2: float
    exit_accel_rms_mps2: float
    enter_gyro_rms_radps: float
    exit_gyro_rms_radps: float
    gravity_tolerance_mps2: float
    enter_persistence_s: float
    exit_persistence_s: float


@dataclass(frozen=True)
class MotionStateObservation:
    state: MotionState
    accel_rms_mps2: float
    gyro_rms_radps: float
    gravity_deviation_mps2: float
    stationary_confidence_s: float


class MotionStateDetector:
    """Causal windowed detector with persistence and release hysteresis."""

    def __init__(self, settings: MotionStateSettings) -> None:
        values = (
            settings.window_s,
            settings.enter_accel_rms_mps2,
            settings.exit_accel_rms_mps2,
            settings.enter_gyro_rms_radps,
            settings.exit_gyro_rms_radps,
            settings.gravity_tolerance_mps2,
            settings.enter_persistence_s,
            settings.exit_persistence_s,
        )
        if not all(np.isfinite(values)) or any(value <= 0 for value in values):
            raise ValueError("Motion-state settings must be finite and positive.")
        if settings.exit_accel_rms_mps2 <= settings.enter_accel_rms_mps2:
            raise ValueError("Exit acceleration threshold must exceed entry threshold.")
        if settings.exit_gyro_rms_radps <= settings.enter_gyro_rms_radps:
            raise ValueError("Exit gyro threshold must exceed entry threshold.")
        self.settings = settings
        self.state = MotionState.MOVING
        self._window: deque[tuple[float, float, float, float]] = deque()
        self._window_duration_s = 0.0
        self._enter_duration_s = 0.0
        self._exit_duration_s = 0.0

    def update(
        self,
        horizontal_accel_mps2: float,
        gyro_magnitude_radps: float,
        gravity_magnitude_mps2: float,
        dt_s: float,
    ) -> MotionStateObservation:
        values = (horizontal_accel_mps2, gyro_magnitude_radps, gravity_magnitude_mps2, dt_s)
        if not all(np.isfinite(values)) or dt_s <= 0:
            raise ValueError("Motion-state inputs must be finite with positive dt.")
        entry = (
            float(dt_s),
            float(horizontal_accel_mps2) ** 2,
            float(gyro_magnitude_radps) ** 2,
            abs(float(gravity_magnitude_mps2) - 9.80665),
        )
        self._window.append(entry)
        self._window_duration_s += entry[0]
        while len(self._window) > 1 and self._window_duration_s - self._window[0][0] >= self.settings.window_s:
            removed = self._window.popleft()
            self._window_duration_s -= removed[0]
        weights = np.array([row[0] for row in self._window], dtype=float)
        accel_rms = float(np.sqrt(np.average([row[1] for row in self._window], weights=weights)))
        gyro_rms = float(np.sqrt(np.average([row[2] for row in self._window], weights=weights)))
        gravity_deviation = float(max(row[3] for row in self._window))
        window_ready = self._window_duration_s >= self.settings.window_s * 0.9
        low_dynamics = (
            window_ready
            and accel_rms <= self.settings.enter_accel_rms_mps2
            and gyro_rms <= self.settings.enter_gyro_rms_radps
            and gravity_deviation <= self.settings.gravity_tolerance_mps2
        )
        release = (
            accel_rms >= self.settings.exit_accel_rms_mps2
            or gyro_rms >= self.settings.exit_gyro_rms_radps
            or gravity_deviation > self.settings.gravity_tolerance_mps2
        )
        if self.state is MotionState.LIKELY_STATIONARY:
            self._exit_duration_s = self._exit_duration_s + dt_s if release else 0.0
            if self._exit_duration_s >= self.settings.exit_persistence_s:
                self.state = MotionState.MOVING
                self._enter_duration_s = 0.0
                self._exit_duration_s = 0.0
        else:
            self._enter_duration_s = self._enter_duration_s + dt_s if low_dynamics else 0.0
            self.state = MotionState.LOW_DYNAMICS if low_dynamics else MotionState.MOVING
            if self._enter_duration_s >= self.settings.enter_persistence_s:
                self.state = MotionState.LIKELY_STATIONARY
                self._exit_duration_s = 0.0
        return MotionStateObservation(
            state=self.state,
            accel_rms_mps2=accel_rms,
            gyro_rms_radps=gyro_rms,
            gravity_deviation_mps2=gravity_deviation,
            stationary_confidence_s=self._enter_duration_s,
        )
