"""Six-state planar vehicle EKF with scalar innovation gating.

The state is ``[east_m, north_m, speed_mps, yaw_rad,
forward_accel_bias_mps2, gyro_yaw_bias_radps]``. Yaw is clockwise from North.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np


EAST, NORTH, SPEED, YAW, ACCEL_BIAS, GYRO_BIAS = range(6)


def wrap_angle_rad(value: float | np.ndarray) -> float | np.ndarray:
    """Wrap radians to the half-open interval [-pi, pi)."""

    wrapped = (np.asarray(value) + np.pi) % (2.0 * np.pi) - np.pi
    return float(wrapped) if wrapped.ndim == 0 else wrapped


@dataclass(frozen=True)
class EKFNoiseConfig:
    acceleration_noise_std_mps2: float
    yaw_rate_noise_std_radps: float
    accel_bias_random_walk_std_mps2_sqrt_s: float
    gyro_bias_random_walk_std_radps_sqrt_s: float
    stationary_speed_std_mps: float
    heading_std_deg: float
    speed_gate_nis: float
    heading_gate_nis: float
    stationary_gate_nis: float
    minimum_variance: float = 1e-9

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "EKFNoiseConfig":
        process = values["process_noise"]
        measurement = values["measurements"]
        gating = values["innovation_gating"]
        return cls(
            acceleration_noise_std_mps2=float(process["acceleration_std_mps2"]),
            yaw_rate_noise_std_radps=float(process["yaw_rate_std_radps"]),
            accel_bias_random_walk_std_mps2_sqrt_s=float(
                process["accel_bias_random_walk_std_mps2_sqrt_s"]
            ),
            gyro_bias_random_walk_std_radps_sqrt_s=float(
                process["gyro_bias_random_walk_std_radps_sqrt_s"]
            ),
            stationary_speed_std_mps=float(measurement["stationary_speed_std_mps"]),
            heading_std_deg=float(measurement["heading_std_deg"]),
            speed_gate_nis=float(gating["speed_nis_threshold"]),
            heading_gate_nis=float(gating["heading_nis_threshold"]),
            stationary_gate_nis=float(gating["stationary_nis_threshold"]),
            minimum_variance=float(values.get("minimum_variance", 1e-9)),
        )

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class MeasurementResult:
    accepted: bool
    innovation: float
    innovation_variance: float
    normalized_innovation_squared: float
    kalman_gain: tuple[float, ...]


class VehicleEKF:
    """Numerically checked planar EKF using actual sample intervals."""

    state_size = 6

    def __init__(
        self,
        state: np.ndarray,
        covariance: np.ndarray,
        noise: EKFNoiseConfig,
        *,
        enforce_nonnegative_speed: bool = True,
    ) -> None:
        self.state = np.asarray(state, dtype=float).copy()
        self.covariance = np.asarray(covariance, dtype=float).copy()
        self.noise = noise
        self.enforce_nonnegative_speed = bool(enforce_nonnegative_speed)
        if self.state.shape != (6,) or self.covariance.shape != (6, 6):
            raise ValueError("EKF state/covariance shapes must be (6,) and (6, 6).")
        self._stabilize_and_validate()

    @classmethod
    def initialized(
        cls,
        *,
        speed_mps: float,
        yaw_deg: float,
        accel_bias_mps2: float,
        gyro_bias_radps: float,
        position_sigma_m: float,
        speed_sigma_mps: float,
        yaw_sigma_deg: float,
        accel_bias_sigma_mps2: float,
        gyro_bias_sigma_radps: float,
        noise: EKFNoiseConfig,
    ) -> "VehicleEKF":
        sigmas = np.array(
            [
                position_sigma_m,
                position_sigma_m,
                speed_sigma_mps,
                np.radians(yaw_sigma_deg),
                accel_bias_sigma_mps2,
                gyro_bias_sigma_radps,
            ],
            dtype=float,
        )
        if not np.all(np.isfinite(sigmas)) or np.any(sigmas <= 0):
            raise ValueError("Initial EKF standard deviations must be finite and positive.")
        state = np.array(
            [0.0, 0.0, speed_mps, np.radians(yaw_deg), accel_bias_mps2, gyro_bias_radps],
            dtype=float,
        )
        return cls(state, np.diag(np.square(sigmas)), noise)

    @property
    def horizontal_position_sigma_m(self) -> float:
        return float(np.sqrt(max(0.0, self.covariance[EAST, EAST] + self.covariance[NORTH, NORTH])))

    def predict(self, forward_acceleration_mps2: float, yaw_rate_radps: float, dt_s: float) -> None:
        if not np.isfinite(dt_s) or dt_s <= 0:
            raise ValueError("EKF dt must be finite and positive.")
        if not np.isfinite(forward_acceleration_mps2) or not np.isfinite(yaw_rate_radps):
            raise ValueError("EKF control inputs must be finite.")

        east, north, speed, yaw, accel_bias, gyro_bias = self.state
        corrected_accel = forward_acceleration_mps2 - accel_bias
        corrected_yaw_rate = yaw_rate_radps - gyro_bias
        travel = speed * dt_s + 0.5 * corrected_accel * dt_s * dt_s
        sin_yaw = np.sin(yaw)
        cos_yaw = np.cos(yaw)
        predicted = self.state.copy()
        predicted[EAST] = east + travel * sin_yaw
        predicted[NORTH] = north + travel * cos_yaw
        predicted[SPEED] = speed + corrected_accel * dt_s
        predicted[YAW] = wrap_angle_rad(yaw + corrected_yaw_rate * dt_s)

        jacobian = np.eye(6, dtype=float)
        jacobian[EAST, SPEED] = dt_s * sin_yaw
        jacobian[EAST, YAW] = travel * cos_yaw
        jacobian[EAST, ACCEL_BIAS] = -0.5 * dt_s * dt_s * sin_yaw
        jacobian[NORTH, SPEED] = dt_s * cos_yaw
        jacobian[NORTH, YAW] = -travel * sin_yaw
        jacobian[NORTH, ACCEL_BIAS] = -0.5 * dt_s * dt_s * cos_yaw
        jacobian[SPEED, ACCEL_BIAS] = -dt_s
        jacobian[YAW, GYRO_BIAS] = -dt_s

        noise_map = np.zeros((6, 4), dtype=float)
        noise_map[EAST, 0] = 0.5 * dt_s * dt_s * sin_yaw
        noise_map[NORTH, 0] = 0.5 * dt_s * dt_s * cos_yaw
        noise_map[SPEED, 0] = dt_s
        noise_map[YAW, 1] = dt_s
        noise_map[ACCEL_BIAS, 2] = np.sqrt(dt_s)
        noise_map[GYRO_BIAS, 3] = np.sqrt(dt_s)
        variances = np.square(
            [
                self.noise.acceleration_noise_std_mps2,
                self.noise.yaw_rate_noise_std_radps,
                self.noise.accel_bias_random_walk_std_mps2_sqrt_s,
                self.noise.gyro_bias_random_walk_std_radps_sqrt_s,
            ]
        )
        process_covariance = noise_map @ np.diag(variances) @ noise_map.T
        self.state = predicted
        if self.enforce_nonnegative_speed and self.state[SPEED] < 0.0:
            self.state[SPEED] = 0.0
        self.covariance = jacobian @ self.covariance @ jacobian.T + process_covariance
        self._stabilize_and_validate()

    def _scalar_update(
        self,
        value: float,
        state_index: int,
        variance: float,
        gate_nis: float,
        *,
        circular: bool = False,
    ) -> MeasurementResult:
        if not np.isfinite(value) or not np.isfinite(variance) or variance <= 0:
            raise ValueError("Measurement value/variance must be finite and variance positive.")
        if not np.isfinite(gate_nis) or gate_nis <= 0:
            raise ValueError("Innovation gate must be finite and positive.")
        observation = np.zeros(6, dtype=float)
        observation[state_index] = 1.0
        innovation = float(value - self.state[state_index])
        if circular:
            innovation = float(wrap_angle_rad(innovation))
        innovation_variance = float(observation @ self.covariance @ observation + variance)
        if innovation_variance <= 0 or not np.isfinite(innovation_variance):
            raise FloatingPointError("Measurement innovation variance is not positive and finite.")
        nis = float(innovation * innovation / innovation_variance)
        if nis > gate_nis:
            return MeasurementResult(False, innovation, innovation_variance, nis, (0.0,) * 6)

        gain = (self.covariance @ observation) / innovation_variance
        self.state = self.state + gain * innovation
        self.state[YAW] = wrap_angle_rad(self.state[YAW])
        if self.enforce_nonnegative_speed and self.state[SPEED] < 0.0:
            self.state[SPEED] = 0.0
        identity = np.eye(6, dtype=float)
        kh = np.outer(gain, observation)
        # Joseph form is stable and preserves positive semidefiniteness better
        # than the simplified P = (I-KH)P expression.
        residual_map = identity - kh
        self.covariance = (
            residual_map @ self.covariance @ residual_map.T
            + np.outer(gain, gain) * variance
        )
        self._stabilize_and_validate()
        return MeasurementResult(True, innovation, innovation_variance, nis, tuple(float(v) for v in gain))

    def update_speed(
        self, speed_mps: float, variance_mps2: float, gate_nis: float | None = None
    ) -> MeasurementResult:
        return self._scalar_update(
            speed_mps,
            SPEED,
            variance_mps2,
            self.noise.speed_gate_nis if gate_nis is None else gate_nis,
        )

    def update_stationary(self) -> MeasurementResult:
        return self._scalar_update(
            0.0,
            SPEED,
            self.noise.stationary_speed_std_mps**2,
            self.noise.stationary_gate_nis,
        )

    def update_heading_deg(
        self, heading_deg: float, variance_deg2: float | None = None
    ) -> MeasurementResult:
        variance = (
            np.radians(self.noise.heading_std_deg) ** 2
            if variance_deg2 is None
            else np.radians(np.sqrt(variance_deg2)) ** 2
        )
        return self._scalar_update(
            np.radians(heading_deg), YAW, float(variance), self.noise.heading_gate_nis, circular=True
        )

    def _stabilize_and_validate(self) -> None:
        self.covariance = 0.5 * (self.covariance + self.covariance.T)
        diagonal = np.diag(self.covariance).copy()
        if np.any(diagonal < -1e-10):
            raise FloatingPointError("EKF covariance has a negative diagonal variance.")
        for index in range(6):
            if self.covariance[index, index] < self.noise.minimum_variance:
                self.covariance[index, index] = self.noise.minimum_variance
        if not np.all(np.isfinite(self.state)) or not np.all(np.isfinite(self.covariance)):
            raise FloatingPointError("EKF state/covariance contains NaN or infinity.")
        if not np.allclose(self.covariance, self.covariance.T, rtol=0.0, atol=1e-10):
            raise FloatingPointError("EKF covariance is not symmetric.")
