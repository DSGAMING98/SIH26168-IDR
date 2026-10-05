from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from idr.blackout import (  # noqa: E402
    GNSS_DERIVED_FIELDS,
    IMU_FIELDS,
    BlackoutWindow,
    create_blackout_experiment,
    reference_blackout_distance_m,
    validate_experiment,
)
from idr.io_vnbd import load_journey, sha256_file  # noqa: E402


class BlackoutSimulatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.journey = load_journey("S1", ROOT)
        cls.window = BlackoutWindow(4215.0, 60.0)
        cls.experiment = create_blackout_experiment(cls.journey, cls.window)

    def test_requested_samples_are_marked_unavailable(self) -> None:
        runtime = self.experiment.runtime.sensor_data
        requested = (runtime["elapsed_s"] >= 4215.0) & (runtime["elapsed_s"] < 4275.0)
        self.assertTrue((~runtime.loc[requested, "gnss_available"]).all())
        self.assertEqual(int(requested.sum()), self.experiment.metadata.masked_sample_count)

    def test_samples_outside_blackout_remain_available(self) -> None:
        runtime = self.experiment.runtime.sensor_data
        requested = (runtime["elapsed_s"] >= 4215.0) & (runtime["elapsed_s"] < 4275.0)
        self.assertTrue(runtime.loc[~requested, "gnss_available"].all())

    def test_blackout_runtime_prevents_gnss_leakage(self) -> None:
        runtime = self.experiment.runtime
        self.assertTrue(set(GNSS_DERIVED_FIELDS).isdisjoint(runtime.sensor_data.columns))
        inside_observations = runtime.gnss_observations[
            (runtime.gnss_observations["elapsed_s"] >= 4215.0)
            & (runtime.gnss_observations["elapsed_s"] < 4275.0)
        ]
        self.assertTrue(inside_observations.empty)

    def test_imu_measurements_remain_available_and_unchanged(self) -> None:
        runtime_imu = self.experiment.runtime.sensor_data.loc[:, list(IMU_FIELDS)]
        source_imu = self.journey.smartphone.loc[:, list(IMU_FIELDS)]
        pd.testing.assert_frame_equal(runtime_imu, source_imu)
        self.assertFalse(runtime_imu.isna().any().any())

    def test_vbox_reference_is_preserved_but_not_in_runtime(self) -> None:
        reference = self.experiment.reference.data.drop(columns=["runtime_elapsed_s", "is_blackout"])
        pd.testing.assert_frame_equal(reference, self.journey.vehicle)
        self.assertFalse(hasattr(self.experiment.runtime, "reference"))
        self.assertNotIn("latitude_deg", self.experiment.runtime.sensor_data.columns)

    def test_original_dataset_files_are_unchanged(self) -> None:
        self.assertEqual(
            sha256_file(self.journey.smartphone_path),
            "8c4d2678fd79cce7c819437a7d85d7d5cb9e47a63dac7d171ead3f9d052deff1",
        )
        self.assertEqual(
            sha256_file(self.journey.vehicle_path),
            "29e92ed9bcb2d711e651246675c435b3f9499c040cfcad367624e8720c0dc891",
        )

    def test_actual_duration_is_within_one_sample_interval(self) -> None:
        metadata = self.experiment.metadata
        self.assertLessEqual(
            abs(metadata.actual_masked_duration_s - metadata.requested_duration_s),
            metadata.sampling_tolerance_s + 1e-9,
        )
        self.assertEqual(metadata.interval_semantics, "half-open [start_s, start_s + duration_s)")
        self.assertLess(
            metadata.actual_first_masked_timestamp_local,
            metadata.actual_end_exclusive_timestamp_local,
        )

    def test_out_of_range_blackouts_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "before the session"):
            create_blackout_experiment(self.journey, BlackoutWindow(-0.1, 10.0))
        with self.assertRaisesRegex(ValueError, "after the session"):
            create_blackout_experiment(self.journey, BlackoutWindow(5170.0, 10.0))

    def test_negative_duration_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            create_blackout_experiment(self.journey, BlackoutWindow(10.0, -1.0))

    def test_zero_duration_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            create_blackout_experiment(self.journey, BlackoutWindow(10.0, 0.0))

    def test_repeated_execution_produces_identical_mask(self) -> None:
        repeated = create_blackout_experiment(self.journey, self.window)
        np.testing.assert_array_equal(
            self.experiment.runtime.sensor_data["gnss_available"].to_numpy(),
            repeated.runtime.sensor_data["gnss_available"].to_numpy(),
        )
        self.assertEqual(self.experiment.metadata, repeated.metadata)

    def test_runtime_and_reference_timestamps_remain_aligned(self) -> None:
        runtime = self.experiment.runtime.sensor_data
        reference = self.experiment.reference.data
        self.assertEqual(len(runtime), len(reference))
        np.testing.assert_array_equal(runtime["elapsed_s"], reference["runtime_elapsed_s"])

    def test_validation_and_reference_distance(self) -> None:
        checks = validate_experiment(self.journey, self.experiment)
        self.assertTrue(all(value for value in checks.values() if isinstance(value, bool)))
        self.assertAlmostEqual(reference_blackout_distance_m(self.experiment), 262.793944, places=5)

    def test_standard_config_and_custom_45_second_window(self) -> None:
        config = json.loads((ROOT / "configs" / "blackouts" / "io_vnbd_s1.json").read_text(encoding="utf-8"))
        standards = [item for item in config["scenarios"] if item["standard"]]
        self.assertEqual({item["duration_s"] for item in standards}, {10.0, 30.0, 60.0, 120.0})
        custom = create_blackout_experiment(self.journey, BlackoutWindow(4850.0, 45.0))
        self.assertLessEqual(abs(custom.metadata.actual_masked_duration_s - 45.0), custom.metadata.sampling_tolerance_s + 1e-9)


if __name__ == "__main__":
    unittest.main()
