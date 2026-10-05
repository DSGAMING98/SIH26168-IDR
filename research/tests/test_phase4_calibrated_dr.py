from __future__ import annotations

import inspect
import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from idr.attitude import (  # noqa: E402
    circular_mean_deg,
    circular_median_deg,
    gravity_euler_diagnostics,
    gravity_roll_pitch_deg,
    gravity_vehicle_basis,
    signed_angle_difference_deg,
)
from idr.blackout import BlackoutWindow, create_blackout_experiment  # noqa: E402
from idr.calibrated_dr import (  # noqa: E402
    Phase4Calibration,
    Phase4Settings,
    as_raw_prediction,
    build_phase4_calibration,
    integrate_calibrated_dead_reckoning,
)
from idr.dead_reckoning import (  # noqa: E402
    PhoneInitialization,
    build_phone_initialization,
    extract_blackout_sensor_data,
    integrate_raw_dead_reckoning,
)
from idr.io_vnbd import load_journey  # noqa: E402
from idr.motion_state import (  # noqa: E402
    MotionState,
    MotionStateDetector,
    MotionStateSettings,
)
from idr.raw_dr_evaluation import evaluate_raw_dr_prediction  # noqa: E402
from idr.signal_conditioning import causal_low_pass  # noqa: E402


def _settings() -> Phase4Settings:
    values = json.loads(
        (ROOT / "configs" / "phase4" / "io_vnbd_s1_classical.json").read_text(
            encoding="utf-8"
        )
    )
    return Phase4Settings.from_dict(values)


def _initialization(speed_mps: float = 0.0, heading_deg: float = 0.0) -> PhoneInitialization:
    return PhoneInitialization(
        blackout_start_s=0.0,
        observation_elapsed_s=0.0,
        observation_timestamp_local="2026-01-01T00:00:00",
        gnss_observation_age_s=0.0,
        solution_change_elapsed_s=0.0,
        solution_change_timestamp_local="2026-01-01T00:00:00",
        gnss_solution_change_age_s=0.0,
        origin_latitude_deg=52.0,
        origin_longitude_deg=-1.5,
        initial_speed_mps=speed_mps,
        initial_heading_deg=heading_deg,
        heading_source="synthetic runtime-safe initialization",
        initial_acceleration_east_mps2=0.0,
        initial_acceleration_north_mps2=0.0,
    )


def _calibration(speed_mps: float = 0.0, heading_deg: float = 0.0) -> Phase4Calibration:
    return Phase4Calibration(
        initialization=_initialization(speed_mps, heading_deg),
        blackout_start_s=0.0,
        calibration_start_s=-10.0,
        calibration_end_s_exclusive=0.0,
        calibration_sensor_samples=100,
        calibration_gnss_rows=100,
        distinct_gnss_solution_rows=4,
        valid_moving_yaw_anchors=4,
        mounting_yaw_offset_deg=heading_deg,
        yaw_dispersion_deg=1.0,
        yaw_resultant_length=0.99,
        yaw_calibration_reliable=True,
        yaw_fallback_reason=None,
        initial_calibrated_heading_deg=heading_deg,
        accelerometer_bias_forward_mps2=0.0,
        accelerometer_bias_left_mps2=0.0,
        gyroscope_bias_radps=0.0,
        bias_stationary_samples=0,
        bias_calibration_reliable=False,
        gyro_axis_verification_interval_count=3,
        gyro_axis_course_correlations={"x": 0.0, "y": -1.0, "z": 0.0},
        gyro_axis_course_scales={"x": 0.0, "y": -1.0, "z": 0.0},
        configured_gyro_axis="y",
        configured_gyro_course_scale=-1.0,
        last_sensor_elapsed_s=0.0,
        last_magnetic_magnitude_ut=40.0,
        last_orientation_azimuth_deg=0.0,
    )


def _sensor_frame(
    elapsed_s: list[float],
    acceleration_forward_mps2: float = 0.0,
    gyro_y_radps: float = 0.0,
    azimuth_deg: float = 0.0,
    gnss_available: bool = False,
) -> pd.DataFrame:
    count = len(elapsed_s)
    return pd.DataFrame(
        {
            "elapsed_s": elapsed_s,
            "time_since_start_ms": np.asarray(elapsed_s) * 1000.0,
            "timestamp_local": pd.date_range("2026-01-01", periods=count, freq="100ms"),
            "accelerometer_x_mps2": np.full(count, acceleration_forward_mps2),
            "accelerometer_y_mps2": np.zeros(count),
            "accelerometer_z_mps2": np.full(count, 9.80665),
            "gravity_x_mps2": np.zeros(count),
            "gravity_y_mps2": np.zeros(count),
            "gravity_z_mps2": np.full(count, 9.80665),
            "gyroscope_x_radps": np.zeros(count),
            "gyroscope_y_radps": np.full(count, gyro_y_radps),
            "gyroscope_z_radps": np.zeros(count),
            "magnetic_field_x_ut": np.full(count, 30.0),
            "magnetic_field_y_ut": np.zeros(count),
            "magnetic_field_z_ut": np.full(count, np.sqrt(700.0)),
            "orientation_azimuth_deg": np.full(count, azimuth_deg),
            "orientation_pitch_deg": np.zeros(count),
            "orientation_roll_deg": np.zeros(count),
            "gnss_available": np.full(count, gnss_available),
        }
    )


class AttitudeTests(unittest.TestCase):
    def test_gravity_derived_roll_pitch_sanity(self) -> None:
        roll, pitch = gravity_roll_pitch_deg([0.0, 0.0, 9.80665])
        self.assertAlmostEqual(float(roll), 0.0, places=12)
        self.assertAlmostEqual(float(pitch), 0.0, places=12)
        roll, _ = gravity_roll_pitch_deg([0.0, 1.0, 1.0])
        self.assertAlmostEqual(float(roll), 45.0, places=12)

    def test_circular_mean_and_median_cross_north(self) -> None:
        mean, dispersion, resultant = circular_mean_deg([359.0, 0.0, 1.0])
        self.assertTrue(mean < 1e-9 or mean > 359.999999)
        self.assertLess(dispersion, 2.0)
        self.assertGreater(resultant, 0.99)
        self.assertEqual(circular_median_deg([359.0, 0.0, 1.0]), 0.0)

    def test_heading_wraparound_uses_short_rotation(self) -> None:
        self.assertAlmostEqual(float(signed_angle_difference_deg(0.0, 359.0)), 1.0)
        self.assertAlmostEqual(float(signed_angle_difference_deg(359.0, 0.0)), -1.0)

    def test_gravity_vehicle_basis_is_orthonormal(self) -> None:
        forward, left, up = gravity_vehicle_basis([0.0, 0.0, 9.80665])
        np.testing.assert_allclose(forward, [1.0, 0.0, 0.0], atol=1e-12)
        np.testing.assert_allclose(left, [0.0, 1.0, 0.0], atol=1e-12)
        np.testing.assert_allclose(up, [0.0, 0.0, 1.0], atol=1e-12)

    def test_gravity_euler_identity_agrees(self) -> None:
        result = gravity_euler_diagnostics(
            np.array([[0.0, 0.0, 9.80665]]), [0.0], [0.0], [0.0]
        )
        self.assertAlmostEqual(float(result["gravity_euler_disagreement_deg"][0]), 0.0)


class SignalConditioningTests(unittest.TestCase):
    def test_filter_is_causal(self) -> None:
        prefix = np.array([[0.0], [1.0], [0.5]])
        first = causal_low_pass(prefix, np.full(3, 0.1), 1.0)
        extended = causal_low_pass(
            np.vstack((prefix, [[1000.0]])), np.full(4, 0.1), 1.0
        )
        np.testing.assert_allclose(first, extended[:3], atol=0.0)

    def test_filter_preserves_constant_signal(self) -> None:
        values = np.full((20, 2), [2.5, -1.5])
        filtered = causal_low_pass(values, np.full(20, 0.1), 1.0)
        np.testing.assert_allclose(filtered, values, atol=1e-12)


class MotionStateTests(unittest.TestCase):
    def _motion_settings(self) -> MotionStateSettings:
        return MotionStateSettings(0.2, 0.2, 0.5, 0.02, 0.05, 0.1, 0.3, 0.3)

    def test_stationary_detector_positive_case(self) -> None:
        detector = MotionStateDetector(self._motion_settings())
        states = [detector.update(0.01, 0.001, 9.80665, 0.1).state for _ in range(10)]
        self.assertEqual(states[-1], MotionState.LIKELY_STATIONARY)

    def test_stationary_detector_moving_case(self) -> None:
        detector = MotionStateDetector(self._motion_settings())
        states = [detector.update(1.0, 0.2, 9.80665, 0.1).state for _ in range(10)]
        self.assertNotIn(MotionState.LIKELY_STATIONARY, states)

    def test_stationary_hysteresis_prevents_single_sample_release(self) -> None:
        detector = MotionStateDetector(self._motion_settings())
        for _ in range(10):
            detector.update(0.0, 0.0, 9.80665, 0.1)
        self.assertEqual(detector.state, MotionState.LIKELY_STATIONARY)
        detector.update(5.0, 1.0, 9.80665, 0.1)
        self.assertEqual(detector.state, MotionState.LIKELY_STATIONARY)
        for _ in range(5):
            detector.update(5.0, 1.0, 9.80665, 0.1)
        self.assertEqual(detector.state, MotionState.MOVING)


class CalibratedSyntheticTests(unittest.TestCase):
    def test_mounting_yaw_calibration_synthetic(self) -> None:
        sensor = _sensor_frame(list(np.arange(0.0, 10.0, 0.1)))
        sensor["orientation_azimuth_deg"] = np.arange(len(sensor), dtype=float)
        course = (sensor["orientation_azimuth_deg"] + 20.0) % 360.0
        gnss = pd.DataFrame(
            {
                "elapsed_s": sensor["elapsed_s"],
                "gps_latitude_deg": np.full(len(sensor), 52.0),
                "gps_longitude_deg": np.full(len(sensor), -1.5),
                "gps_speed_mps": np.full(len(sensor), 10.0),
                "gps_orientation_deg": course,
            }
        )
        calibration = build_phase4_calibration(sensor, gnss, 10.0, _settings())
        self.assertTrue(calibration.yaw_calibration_reliable)
        self.assertAlmostEqual(calibration.mounting_yaw_offset_deg, 20.0, places=9)

    def test_constant_gyro_yaw_rate_integration(self) -> None:
        frame = _sensor_frame(
            list(np.arange(0.1, 1.01, 0.1)), gyro_y_radps=-np.radians(10.0)
        )
        prediction = integrate_calibrated_dead_reckoning(
            frame, _calibration(), _settings(), "V3_HEADING_STABILIZED"
        ).data
        self.assertAlmostEqual(float(prediction["stabilized_heading_deg"].iloc[-1]), 10.0, places=9)

    def test_zero_velocity_update_only_when_stationary(self) -> None:
        motion = MotionStateSettings(0.2, 0.2, 0.5, 0.02, 0.05, 0.1, 0.3, 0.3)
        settings = replace(_settings(), motion=motion)
        frame = _sensor_frame(list(np.arange(0.1, 1.51, 0.1)))
        stationary = integrate_calibrated_dead_reckoning(
            frame, _calibration(speed_mps=5.0), settings, "V4_MOTION_AWARE"
        ).data
        orientation_only = integrate_calibrated_dead_reckoning(
            frame, _calibration(speed_mps=5.0), settings, "V1_ORIENTATION_ALIGNMENT"
        ).data
        self.assertTrue(bool(stationary["zupt_applied"].any()))
        self.assertAlmostEqual(float(stationary["estimated_speed_mps"].iloc[-1]), 0.0)
        self.assertFalse(bool(orientation_only["zupt_applied"].any()))
        self.assertGreater(float(orientation_only["estimated_speed_mps"].iloc[-1]), 0.0)

    def test_estimator_works_without_reference(self) -> None:
        parameters = inspect.signature(integrate_calibrated_dead_reckoning).parameters
        self.assertEqual(
            set(parameters), {"blackout_sensor_data", "calibration", "settings", "variant"}
        )
        prediction = integrate_calibrated_dead_reckoning(
            _sensor_frame([0.1]), _calibration(), _settings()
        )
        self.assertFalse(hasattr(prediction, "reference"))

    def test_estimator_rejects_reference_leakage(self) -> None:
        frame = _sensor_frame([0.1, 0.2])
        frame["latitude_deg"] = 52.0
        with self.assertRaisesRegex(ValueError, "evaluation-reference"):
            integrate_calibrated_dead_reckoning(frame, _calibration(), _settings())

    def test_estimator_rejects_phone_gnss_leakage(self) -> None:
        frame = _sensor_frame([0.1, 0.2])
        frame["gps_latitude_deg"] = 52.0
        with self.assertRaisesRegex(ValueError, "forbidden GNSS"):
            integrate_calibrated_dead_reckoning(frame, _calibration(), _settings())

    def test_calibration_rejects_future_gnss(self) -> None:
        sensor = _sensor_frame(list(np.arange(0.0, 1.0, 0.1)))
        gnss = pd.DataFrame(
            {
                "elapsed_s": [0.0, 1.0],
                "gps_latitude_deg": [52.0, 52.0],
                "gps_longitude_deg": [-1.5, -1.5],
                "gps_speed_mps": [5.0, 5.0],
                "gps_orientation_deg": [0.0, 0.0],
            }
        )
        with self.assertRaisesRegex(ValueError, "blackout or future"):
            build_phase4_calibration(sensor, gnss, 1.0, _settings())

    def test_calibration_rejects_future_sensor_sample(self) -> None:
        sensor = _sensor_frame(list(np.arange(0.0, 1.1, 0.1)))
        gnss = pd.DataFrame(
            {
                "elapsed_s": list(np.arange(0.0, 1.0, 0.1)),
                "gps_latitude_deg": 52.0,
                "gps_longitude_deg": -1.5,
                "gps_speed_mps": 5.0,
                "gps_orientation_deg": 0.0,
            }
        )
        with self.assertRaisesRegex(ValueError, "blackout or future"):
            build_phase4_calibration(sensor, gnss, 1.0, _settings())

    def test_irregular_dt_is_preserved(self) -> None:
        prediction = integrate_calibrated_dead_reckoning(
            _sensor_frame([0.1, 0.25, 0.55]),
            _calibration(speed_mps=2.0, heading_deg=90.0),
            _settings(),
            "V3_HEADING_STABILIZED",
        ).data
        np.testing.assert_allclose(prediction["dt_s"], [0.1, 0.15, 0.3], atol=1e-12)

    def test_repeated_execution_is_deterministic(self) -> None:
        frame = _sensor_frame([0.1, 0.2, 0.3], acceleration_forward_mps2=0.2)
        first = integrate_calibrated_dead_reckoning(frame, _calibration(), _settings()).data
        second = integrate_calibrated_dead_reckoning(frame, _calibration(), _settings()).data
        pd.testing.assert_frame_equal(first, second)


class CalibratedS1RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.journey = load_journey("S1", ROOT)

    def _experiment_inputs(self, start: float, duration: float):
        window = BlackoutWindow(start, duration)
        experiment = create_blackout_experiment(self.journey, window)
        sensor = experiment.runtime.sensor_data
        gnss = experiment.runtime.gnss_observations
        sensor_history = sensor[sensor["elapsed_s"] < start]
        gnss_history = gnss[gnss["elapsed_s"] < start]
        blackout = extract_blackout_sensor_data(experiment.runtime, window)
        return window, experiment, sensor_history, gnss_history, blackout

    def test_raw_phase3_60_second_regression_result(self) -> None:
        window, experiment, sensor, gnss, blackout = self._experiment_inputs(4215.0, 60.0)
        initialization = build_phone_initialization(sensor, gnss, window.start_s)
        raw = integrate_raw_dead_reckoning(blackout, initialization)
        metrics = evaluate_raw_dr_prediction(raw, experiment.reference).metrics
        self.assertAlmostEqual(metrics["final_position_error_m"], 327.1854981423306, places=6)
        self.assertAlmostEqual(metrics["drift_percentage"], 124.50267800862389, places=6)

    def test_real_phase4_benchmark_smoke(self) -> None:
        window, experiment, sensor, gnss, blackout = self._experiment_inputs(4555.0, 30.0)
        calibration = build_phase4_calibration(sensor, gnss, window.start_s, _settings())
        prediction = integrate_calibrated_dead_reckoning(blackout, calibration, _settings())
        self.assertEqual(len(prediction.data), experiment.metadata.masked_sample_count)
        self.assertTrue(np.isfinite(prediction.data.select_dtypes(include=[np.number])).all().all())
        metrics = evaluate_raw_dr_prediction(as_raw_prediction(prediction), experiment.reference).metrics
        self.assertLess(metrics["final_position_error_m"], 135.2966)


if __name__ == "__main__":
    unittest.main()
