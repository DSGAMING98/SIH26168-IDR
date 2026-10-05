from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from idr.fusion.ekf import EKFNoiseConfig, VehicleEKF  # noqa: E402


def _noise() -> EKFNoiseConfig:
    return EKFNoiseConfig(0.2, 0.02, 0.01, 0.001, 0.1, 5.0, 9.0, 9.0, 100.0)


def _ekf(speed: float = 0.0, yaw: float = 0.0) -> VehicleEKF:
    return VehicleEKF.initialized(
        speed_mps=speed,
        yaw_deg=yaw,
        accel_bias_mps2=0.0,
        gyro_bias_radps=0.0,
        position_sigma_m=1.0,
        speed_sigma_mps=2.0,
        yaw_sigma_deg=10.0,
        accel_bias_sigma_mps2=0.2,
        gyro_bias_sigma_radps=0.02,
        noise=_noise(),
    )


class VehicleEKFTests(unittest.TestCase):
    def test_constant_velocity_straight_motion(self) -> None:
        ekf = _ekf(10.0, 90.0)
        ekf.predict(0.0, 0.0, 1.0)
        self.assertAlmostEqual(ekf.state[0], 10.0, places=9)
        self.assertAlmostEqual(ekf.state[1], 0.0, places=9)

    def test_constant_acceleration(self) -> None:
        ekf = _ekf(0.0, 90.0)
        ekf.predict(1.0, 0.0, 2.0)
        self.assertAlmostEqual(ekf.state[0], 2.0, places=9)
        self.assertAlmostEqual(ekf.state[2], 2.0, places=9)

    def test_constant_yaw_rate_turn(self) -> None:
        ekf = _ekf(1.0, 0.0)
        ekf.predict(0.0, np.pi / 2.0, 1.0)
        self.assertAlmostEqual(np.degrees(ekf.state[3]), 90.0, places=9)

    def test_zero_velocity_stationary_update(self) -> None:
        ekf = _ekf(1.0)
        before = ekf.state[2]
        result = ekf.update_stationary()
        self.assertTrue(result.accepted)
        self.assertLess(ekf.state[2], before)

    def test_known_speed_measurement_update(self) -> None:
        ekf = _ekf(4.0)
        result = ekf.update_speed(6.0, 1.0)
        self.assertTrue(result.accepted)
        self.assertGreater(ekf.state[2], 4.0)
        self.assertLess(ekf.state[2], 6.0)

    def test_heading_wraparound_359_to_zero(self) -> None:
        ekf = _ekf(1.0, 359.0)
        result = ekf.update_heading_deg(1.0, variance_deg2=4.0)
        self.assertTrue(result.accepted)
        self.assertAlmostEqual(np.degrees(result.innovation), 2.0, places=9)

    def test_covariance_remains_finite_and_symmetric(self) -> None:
        ekf = _ekf(5.0, 25.0)
        for dt in (0.1, 0.12, 0.08, 0.15):
            ekf.predict(0.2, 0.01, dt)
        self.assertTrue(np.isfinite(ekf.covariance).all())
        np.testing.assert_allclose(ekf.covariance, ekf.covariance.T, atol=1e-12)
        self.assertTrue((np.diag(ekf.covariance) >= 0.0).all())

    def test_prediction_only_uncertainty_increases(self) -> None:
        ekf = _ekf(5.0)
        before = ekf.horizontal_position_sigma_m
        for _ in range(20):
            ekf.predict(0.0, 0.0, 0.1)
        self.assertGreater(ekf.horizontal_position_sigma_m, before)

    def test_reliable_measurement_reduces_speed_uncertainty(self) -> None:
        ekf = _ekf(5.0)
        before = ekf.covariance[2, 2]
        ekf.update_speed(5.0, 0.25)
        self.assertLess(ekf.covariance[2, 2], before)

    def test_rejected_measurement_does_not_corrupt_state(self) -> None:
        ekf = _ekf(5.0)
        state = ekf.state.copy()
        covariance = ekf.covariance.copy()
        result = ekf.update_speed(1000.0, 0.01)
        self.assertFalse(result.accepted)
        np.testing.assert_array_equal(ekf.state, state)
        np.testing.assert_array_equal(ekf.covariance, covariance)

    def test_irregular_dt_is_used(self) -> None:
        ekf = _ekf(2.0, 90.0)
        for dt in (0.1, 0.3, 0.2):
            ekf.predict(0.0, 0.0, dt)
        self.assertAlmostEqual(ekf.state[0], 1.2, places=9)

    def test_invalid_dt_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "dt"):
            _ekf().predict(0.0, 0.0, 0.0)

    def test_deterministic_execution(self) -> None:
        first = _ekf(3.0, 15.0)
        second = _ekf(3.0, 15.0)
        for ekf in (first, second):
            ekf.predict(0.3, -0.02, 0.17)
            ekf.update_speed(3.1, 1.0)
        np.testing.assert_array_equal(first.state, second.state)
        np.testing.assert_array_equal(first.covariance, second.covariance)


if __name__ == "__main__":
    unittest.main()
