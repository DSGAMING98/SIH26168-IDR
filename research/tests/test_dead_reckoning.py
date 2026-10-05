from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from idr.blackout import BlackoutWindow, create_blackout_experiment  # noqa: E402
from idr.dead_reckoning import (  # noqa: E402
    PhoneInitialization,
    build_phone_initialization,
    extract_blackout_sensor_data,
    integrate_raw_dead_reckoning,
)
from idr.io_vnbd import load_journey  # noqa: E402
from idr.orientation import rotate_device_to_enu  # noqa: E402


def _initialization(
    speed_mps: float = 0.0,
    heading_deg: float = 0.0,
    acceleration_east_mps2: float = 0.0,
    acceleration_north_mps2: float = 0.0,
) -> PhoneInitialization:
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
        heading_source="synthetic",
        initial_acceleration_east_mps2=acceleration_east_mps2,
        initial_acceleration_north_mps2=acceleration_north_mps2,
    )


def _sensor_frame(
    elapsed_s: list[float],
    acceleration_device: tuple[float, float, float] = (0.0, 0.0, 0.0),
    azimuth_deg: float = 0.0,
    pitch_deg: float = 0.0,
    roll_deg: float = 0.0,
) -> pd.DataFrame:
    count = len(elapsed_s)
    return pd.DataFrame(
        {
            "elapsed_s": elapsed_s,
            "accelerometer_x_mps2": np.full(count, acceleration_device[0]),
            "accelerometer_y_mps2": np.full(count, acceleration_device[1]),
            "accelerometer_z_mps2": np.full(count, acceleration_device[2] + 9.80665),
            "gravity_x_mps2": np.zeros(count),
            "gravity_y_mps2": np.zeros(count),
            "gravity_z_mps2": np.full(count, 9.80665),
            "orientation_azimuth_deg": np.full(count, azimuth_deg),
            "orientation_pitch_deg": np.full(count, pitch_deg),
            "orientation_roll_deg": np.full(count, roll_deg),
            "gnss_available": np.zeros(count, dtype=bool),
        }
    )


class RawDeadReckoningSyntheticTests(unittest.TestCase):
    def test_stationary_input_remains_fixed(self) -> None:
        prediction = integrate_raw_dead_reckoning(
            _sensor_frame([1.0, 2.0, 3.0]),
            _initialization(),
            max_allowed_dt_s=1.1,
        ).data
        np.testing.assert_allclose(prediction[["estimated_x_m", "estimated_y_m"]], 0.0, atol=1e-12)
        np.testing.assert_allclose(prediction["estimated_speed_mps"], 0.0, atol=1e-12)

    def test_constant_velocity_matches_analytical_displacement(self) -> None:
        prediction = integrate_raw_dead_reckoning(
            _sensor_frame([1.0, 2.0, 3.0]),
            _initialization(speed_mps=2.0, heading_deg=90.0),
            max_allowed_dt_s=1.1,
        ).data
        np.testing.assert_allclose(prediction["estimated_x_m"], [2.0, 4.0, 6.0], atol=1e-12)
        np.testing.assert_allclose(prediction["estimated_y_m"], 0.0, atol=1e-12)

    def test_constant_acceleration_matches_kinematics(self) -> None:
        prediction = integrate_raw_dead_reckoning(
            _sensor_frame([1.0, 2.0, 3.0], acceleration_device=(1.0, 0.0, 0.0)),
            _initialization(acceleration_east_mps2=1.0),
            max_allowed_dt_s=1.1,
        ).data
        np.testing.assert_allclose(prediction["estimated_velocity_x_mps"], [1.0, 2.0, 3.0], atol=1e-12)
        np.testing.assert_allclose(prediction["estimated_x_m"], [0.5, 2.0, 4.5], atol=1e-12)

    def test_irregular_timestamps_use_actual_dt(self) -> None:
        prediction = integrate_raw_dead_reckoning(
            _sensor_frame([0.2, 0.45, 0.8]),
            _initialization(speed_mps=3.0, heading_deg=90.0),
        ).data
        np.testing.assert_allclose(prediction["dt_s"], [0.2, 0.25, 0.35], atol=1e-12)
        np.testing.assert_allclose(prediction["estimated_x_m"], [0.6, 1.35, 2.4], atol=1e-12)

    def test_orientation_identity_preserves_vector(self) -> None:
        rotated = rotate_device_to_enu([1.0, 2.0, 3.0], 0.0, 0.0, 0.0)
        np.testing.assert_allclose(rotated, [1.0, 2.0, 3.0], atol=1e-12)

    def test_android_90_degree_azimuth_maps_device_y_to_east(self) -> None:
        rotated = rotate_device_to_enu([0.0, 1.0, 0.0], 90.0, 0.0, 0.0)
        np.testing.assert_allclose(rotated, [1.0, 0.0, 0.0], atol=1e-12)

    def test_estimator_rejects_gnss_leakage(self) -> None:
        frame = _sensor_frame([0.1, 0.2])
        frame["gps_latitude_deg"] = 52.0
        with self.assertRaisesRegex(ValueError, "forbidden GNSS"):
            integrate_raw_dead_reckoning(frame, _initialization())

    def test_estimator_api_has_no_reference_parameter(self) -> None:
        parameters = inspect.signature(integrate_raw_dead_reckoning).parameters
        self.assertEqual(
            set(parameters),
            {"blackout_sensor_data", "initialization", "max_allowed_dt_s"},
        )
        prediction = integrate_raw_dead_reckoning(
            _sensor_frame([0.1]), _initialization()
        )
        self.assertFalse(hasattr(prediction, "reference"))

    def test_repeated_integration_is_deterministic(self) -> None:
        frame = _sensor_frame([0.1, 0.2, 0.3], acceleration_device=(0.25, -0.5, 0.0))
        first = integrate_raw_dead_reckoning(frame, _initialization()).data
        second = integrate_raw_dead_reckoning(frame, _initialization()).data
        pd.testing.assert_frame_equal(first, second)

    def test_nonpositive_or_implausible_dt_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            integrate_raw_dead_reckoning(_sensor_frame([0.1, 0.1]), _initialization())
        with self.assertRaisesRegex(ValueError, "gap exceeds"):
            integrate_raw_dead_reckoning(_sensor_frame([0.6]), _initialization())


class RawDeadReckoningS1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.journey = load_journey("S1", ROOT)
        cls.window = BlackoutWindow(320.0, 10.0)
        cls.experiment = create_blackout_experiment(cls.journey, cls.window)

    def test_real_s1_smoke_is_finite_aligned_and_reference_free(self) -> None:
        runtime = self.experiment.runtime
        sensor_history = runtime.sensor_data[runtime.sensor_data["elapsed_s"] < self.window.start_s]
        gnss_history = runtime.gnss_observations[runtime.gnss_observations["elapsed_s"] < self.window.start_s]
        initialization = build_phone_initialization(sensor_history, gnss_history, self.window.start_s)
        blackout = extract_blackout_sensor_data(runtime, self.window)
        prediction = integrate_raw_dead_reckoning(blackout, initialization)
        self.assertEqual(len(prediction.data), self.experiment.metadata.masked_sample_count)
        np.testing.assert_array_equal(prediction.data["elapsed_s"], blackout["elapsed_s"])
        self.assertTrue(np.isfinite(prediction.data.select_dtypes(include=[np.number])).all().all())
        self.assertFalse(hasattr(prediction, "reference"))

    def test_initialization_rejects_future_gnss(self) -> None:
        runtime = self.experiment.runtime
        sensor_history = runtime.sensor_data[runtime.sensor_data["elapsed_s"] <= self.window.start_s]
        gnss_history = runtime.gnss_observations
        with self.assertRaisesRegex(ValueError, "blackout or future"):
            build_phone_initialization(sensor_history, gnss_history, self.window.start_s)


if __name__ == "__main__":
    unittest.main()
