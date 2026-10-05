from __future__ import annotations

import inspect
import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import torch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from idr.blackout import BlackoutWindow, create_blackout_experiment  # noqa: E402
from idr.calibrated_dr import Phase4Calibration, Phase4Settings, build_phase4_calibration  # noqa: E402
from idr.dead_reckoning import PhoneInitialization, extract_blackout_sensor_data  # noqa: E402
from idr.fusion.ekf import EKFNoiseConfig, VehicleEKF  # noqa: E402
from idr.hybrid.hybrid_idr import HybridSettings, evaluate_hybrid_prediction, run_hybrid_estimator  # noqa: E402
from idr.io_vnbd import load_journey  # noqa: E402
from idr.ml.features import FEATURE_ORDER  # noqa: E402
from idr.ml.velocity_model import FeatureScaler, VelocityGRU, VelocityModelBundle, VelocityModelConfig, load_velocity_bundle  # noqa: E402
from idr.phase5_pipeline import run_phase5_scenario  # noqa: E402


def _phase4_settings() -> Phase4Settings:
    values = json.loads((ROOT / "configs" / "phase4" / "io_vnbd_s1_classical.json").read_text(encoding="utf-8"))
    return Phase4Settings.from_dict(values)


def _hybrid_settings() -> HybridSettings:
    values = json.loads((ROOT / "configs" / "phase5" / "io_vnbd_s1_ekf.json").read_text(encoding="utf-8"))
    return HybridSettings.from_dict(values)


def _initialization(speed: float = 3.0) -> PhoneInitialization:
    return PhoneInitialization(0.0, 0.0, "2026-01-01T00:00:00", 0.0, 0.0, "2026-01-01T00:00:00", 0.0, 52.0, -1.5, speed, 0.0, "synthetic", 0.0, 0.0)


def _calibration(speed: float = 3.0) -> Phase4Calibration:
    return Phase4Calibration(
        _initialization(speed), 0.0, -60.0, 0.0, 600, 600, 10, 10, 0.0, 1.0, 0.99, True, None, 0.0,
        0.0, 0.0, 0.0, 100, True, 5, {"x": 0.0, "y": -1.0, "z": 0.0},
        {"x": 0.0, "y": -1.0, "z": 0.0}, "y", -1.0, 0.0, 40.0, 0.0,
    )


def _sensor(count: int = 30, acceleration: float = 0.0) -> pd.DataFrame:
    elapsed = np.arange(1, count + 1, dtype=float) * 0.1
    return pd.DataFrame(
        {
            "elapsed_s": elapsed,
            "time_since_start_ms": elapsed * 1000.0,
            "timestamp_local": pd.date_range("2026-01-01", periods=count, freq="100ms"),
            "accelerometer_x_mps2": acceleration,
            "accelerometer_y_mps2": 0.0,
            "accelerometer_z_mps2": 9.80665,
            "gravity_x_mps2": 0.0,
            "gravity_y_mps2": 0.0,
            "gravity_z_mps2": 9.80665,
            "gyroscope_x_radps": 0.0,
            "gyroscope_y_radps": 0.0,
            "gyroscope_z_radps": 0.0,
            "magnetic_field_x_ut": 30.0,
            "magnetic_field_y_ut": 0.0,
            "magnetic_field_z_ut": np.sqrt(700.0),
            "orientation_azimuth_deg": 0.0,
            "orientation_pitch_deg": 0.0,
            "orientation_roll_deg": 0.0,
            "gnss_available": False,
        }
    )


def _ood_bundle() -> VelocityModelBundle:
    config = VelocityModelConfig(len(FEATURE_ORDER), 4, 1, 12.0, 5, 10.0, 1, 1)
    model = VelocityGRU(config).eval()
    with torch.no_grad():
        for parameter in model.parameters():
            parameter.zero_()
        model.output.bias.fill_(0.5)
    scaler = FeatureScaler(FEATURE_ORDER, (0.0,) * 10, (1.0,) * 10, (-1.0,) * 10, (1.0,) * 10)
    return VelocityModelBundle(model, scaler, config, 0.25, {})


class HybridSyntheticTests(unittest.TestCase):
    def test_measurement_uncertainty_changes_kalman_gain(self) -> None:
        kwargs = dict(speed_mps=2.0, yaw_deg=0.0, accel_bias_mps2=0.0, gyro_bias_radps=0.0, position_sigma_m=1.0, speed_sigma_mps=2.0, yaw_sigma_deg=10.0, accel_bias_sigma_mps2=0.2, gyro_bias_sigma_radps=0.02, noise=_hybrid_settings().noise)
        low = VehicleEKF.initialized(**kwargs).update_speed(4.0, 0.1)
        high = VehicleEKF.initialized(**kwargs).update_speed(4.0, 100.0)
        self.assertGreater(low.kalman_gain[2], high.kalman_gain[2])

    def test_extreme_speed_prediction_is_gated(self) -> None:
        ekf = VehicleEKF.initialized(speed_mps=2.0, yaw_deg=0.0, accel_bias_mps2=0.0, gyro_bias_radps=0.0, position_sigma_m=1.0, speed_sigma_mps=1.0, yaw_sigma_deg=10.0, accel_bias_sigma_mps2=0.2, gyro_bias_sigma_radps=0.02, noise=_hybrid_settings().noise)
        self.assertFalse(ekf.update_speed(1000.0, 0.25).accepted)

    def test_ood_input_reduces_ml_influence(self) -> None:
        bundle = _ood_bundle()
        rejected = run_hybrid_estimator(_sensor(10, 20.0), _calibration(), _phase4_settings(), _hybrid_settings(), bundle)
        permissive = run_hybrid_estimator(
            _sensor(10, 20.0),
            _calibration(),
            _phase4_settings(),
            replace(_hybrid_settings(), ood_soft_exceedance=1e9, ood_hard_exceedance=1e10),
            bundle,
        )
        self.assertGreater(int(rejected.data["ml_update_skipped_ood"].sum()), 0)
        self.assertNotEqual(float(rejected.data["estimated_speed_mps"].iloc[-1]), float(permissive.data["estimated_speed_mps"].iloc[-1]))

    def test_stationary_update_remains_functional(self) -> None:
        prediction = run_hybrid_estimator(_sensor(40), _calibration(3.0), _phase4_settings(), _hybrid_settings())
        self.assertGreater(int(prediction.data["stationary_update_accepted"].sum()), 0)
        self.assertLess(float(prediction.data["estimated_speed_mps"].iloc[-1]), 0.1)

    def test_hybrid_trajectory_is_finite_without_reference(self) -> None:
        prediction = run_hybrid_estimator(_sensor(10), _calibration(), _phase4_settings(), _hybrid_settings(), _ood_bundle())
        self.assertTrue(np.isfinite(prediction.data.select_dtypes(include=[np.number])).all().all())
        self.assertFalse(hasattr(prediction, "reference"))

    def test_estimator_signature_has_no_evaluation_reference(self) -> None:
        parameters = inspect.signature(run_hybrid_estimator).parameters
        self.assertNotIn("reference", parameters)
        self.assertNotIn("evaluation_reference", parameters)

    def test_future_gnss_field_is_rejected(self) -> None:
        sensor = _sensor(10)
        sensor["gps_speed_mps"] = 4.0
        with self.assertRaisesRegex(ValueError, "forbidden"):
            run_hybrid_estimator(sensor, _calibration(), _phase4_settings(), _hybrid_settings())


class HybridS1RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.journey = load_journey("S1", ROOT)

    def test_final_checkpoint_reproduces_saved_10_second_result(self) -> None:
        phase4 = _phase4_settings()
        settings = _hybrid_settings()
        bundle = load_velocity_bundle(ROOT / "models" / "phase5" / "io_vnbd_s1" / "velocity_gru.pt")
        run = run_phase5_scenario(self.journey, BlackoutWindow(320.0, 10.0), phase4, settings, bundle)
        saved = json.loads((ROOT / "results" / "phase5" / "io_vnbd" / "s1" / "scenarios" / "s1_10_steady" / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(len(run.hybrid_prediction.data), 100)
        self.assertAlmostEqual(run.hybrid_evaluation.metrics["final_position_error_m"], saved["metrics"]["hybrid"]["final_position_error_m"], places=9)


if __name__ == "__main__":
    unittest.main()
