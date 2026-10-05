from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from idr.blackout import EvaluationReference  # noqa: E402
from idr.dead_reckoning import PhoneInitialization, RawDRPrediction  # noqa: E402
from idr.evaluation import local_xy_to_geodetic  # noqa: E402
from idr.raw_dr_evaluation import evaluate_raw_dr_prediction  # noqa: E402


class RawDREvaluationTests(unittest.TestCase):
    def test_relative_rebasing_removes_preexisting_absolute_offset(self) -> None:
        initialization = PhoneInitialization(
            blackout_start_s=1.0,
            observation_elapsed_s=0.0,
            observation_timestamp_local="2026-01-01T00:00:00",
            gnss_observation_age_s=1.0,
            solution_change_elapsed_s=0.0,
            solution_change_timestamp_local="2026-01-01T00:00:00",
            gnss_solution_change_age_s=1.0,
            origin_latitude_deg=52.0,
            origin_longitude_deg=-1.5,
            initial_speed_mps=1.0,
            initial_heading_deg=90.0,
            heading_source="synthetic",
            initial_acceleration_east_mps2=0.0,
            initial_acceleration_north_mps2=0.0,
        )
        predicted_latitude, predicted_longitude = local_xy_to_geodetic(
            [1.0, 2.0], [0.0, 0.0], 52.0, -1.5
        )
        prediction_data = pd.DataFrame(
            {
                "elapsed_s": [1.0, 2.0],
                "estimated_x_m": [1.0, 2.0],
                "estimated_y_m": [0.0, 0.0],
                "estimated_speed_mps": [1.0, 1.0],
                "local_acceleration_x_mps2": [0.0, 0.0],
                "local_acceleration_y_mps2": [0.0, 0.0],
                "orientation_azimuth_deg": [90.0, 90.0],
                "orientation_pitch_deg": [0.0, 0.0],
                "orientation_roll_deg": [0.0, 0.0],
                "estimated_latitude_deg": predicted_latitude,
                "estimated_longitude_deg": predicted_longitude,
            }
        )
        reference_latitude, reference_longitude = local_xy_to_geodetic(
            [100.0, 101.0, 102.0], [0.0, 0.0, 0.0], 52.0, -1.5
        )
        reference = EvaluationReference(
            pd.DataFrame(
                {
                    "runtime_elapsed_s": [0.0, 1.0, 2.0],
                    "latitude_deg": reference_latitude,
                    "longitude_deg": reference_longitude,
                    "velocity_kmh": [3.6, 3.6, 3.6],
                }
            )
        )
        evaluation = evaluate_raw_dr_prediction(
            RawDRPrediction(prediction_data, initialization), reference
        )
        np.testing.assert_allclose(
            evaluation.timeseries["relative_position_error_m"], 0.0, atol=1e-9
        )
        self.assertAlmostEqual(evaluation.metrics["final_position_error_m"], 0.0, places=9)
        self.assertAlmostEqual(
            evaluation.metrics["absolute_initial_phone_gnss_vbox_offset_m"],
            100.0,
            delta=0.001,
        )


if __name__ == "__main__":
    unittest.main()
