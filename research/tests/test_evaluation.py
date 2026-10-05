from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from idr.evaluation import (  # noqa: E402
    drift_percentage,
    geodetic_to_local_xy_m,
    great_circle_distance_m,
    local_xy_to_geodetic,
    path_distance_m,
    position_error_series_m,
    summarize_position_errors,
)


class EvaluationUtilityTests(unittest.TestCase):
    def test_great_circle_distance_is_symmetric_and_metric(self) -> None:
        forward = float(great_circle_distance_m(0.0, 0.0, 0.0, 1.0))
        reverse = float(great_circle_distance_m(0.0, 1.0, 0.0, 0.0))
        self.assertAlmostEqual(forward, reverse, places=9)
        self.assertAlmostEqual(forward, 111195.08, delta=0.2)

    def test_path_distance_sums_consecutive_segments(self) -> None:
        distance = path_distance_m([0.0, 0.0, 0.0], [0.0, 0.5, 1.0])
        self.assertAlmostEqual(distance, float(great_circle_distance_m(0.0, 0.0, 0.0, 1.0)), places=6)
        self.assertEqual(path_distance_m([1.0], [2.0]), 0.0)

    def test_local_metric_frame_uses_explicit_origin(self) -> None:
        frame = geodetic_to_local_xy_m([52.0, 52.001], [-1.5, -1.499], 52.0, -1.5)
        self.assertEqual(frame.origin_latitude_deg, 52.0)
        self.assertEqual(frame.origin_longitude_deg, -1.5)
        self.assertEqual(frame.method, "local spherical equirectangular approximation")
        self.assertAlmostEqual(frame.x_east_m[0], 0.0)
        self.assertAlmostEqual(frame.y_north_m[0], 0.0)
        self.assertGreater(frame.x_east_m[1], 0.0)
        self.assertGreater(frame.y_north_m[1], 0.0)
        latitude, longitude = local_xy_to_geodetic(
            frame.x_east_m,
            frame.y_north_m,
            frame.origin_latitude_deg,
            frame.origin_longitude_deg,
        )
        np.testing.assert_allclose(latitude, [52.0, 52.001], atol=1e-12)
        np.testing.assert_allclose(longitude, [-1.5, -1.499], atol=1e-12)

    def test_position_error_series_and_summary_metrics(self) -> None:
        errors = np.array([0.0, 3.0, 4.0, 5.0])
        metrics = summarize_position_errors(errors, reference_distance_m=100.0)
        self.assertEqual(metrics.sample_count, 4)
        self.assertEqual(metrics.final_position_error_m, 5.0)
        self.assertEqual(metrics.mean_position_error_m, 3.0)
        self.assertAlmostEqual(metrics.rmse_position_error_m, math.sqrt(12.5))
        self.assertEqual(metrics.maximum_position_error_m, 5.0)
        self.assertAlmostEqual(metrics.p95_position_error_m, 4.85)
        self.assertEqual(metrics.drift_percentage, 5.0)
        series = position_error_series_m([0.0], [0.0], [0.0], [0.001])
        self.assertAlmostEqual(float(series[0]), 111.195, delta=0.01)

    def test_zero_reference_distance_has_undefined_drift(self) -> None:
        self.assertIsNone(drift_percentage(1.0, 0.0))
        self.assertIsNone(summarize_position_errors([0.0], 0.0).drift_percentage)
        with self.assertRaises(ValueError):
            drift_percentage(-1.0, 10.0)
        with self.assertRaises(ValueError):
            drift_percentage(float("nan"), 10.0)


if __name__ == "__main__":
    unittest.main()
