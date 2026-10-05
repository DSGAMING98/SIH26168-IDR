from __future__ import annotations
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from idr.io_vnbd import (  # noqa: E402
    is_git_lfs_pointer,
    load_journey,
    sampling_statistics,
    synchronization_statistics,
)


class IOVNBDLoaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.journey = load_journey("S1", ROOT)

    def test_original_archive_contains_lfs_pointer(self) -> None:
        pointer = (
            ROOT
            / "IO-VNBD-master"
            / "Synchronised V abd S datasets"
            / "Uncategorised IOVNB Dataset"
            / "S-Dataset"
            / "S-S1.csv"
        )
        self.assertTrue(is_git_lfs_pointer(pointer))
        self.assertFalse(is_git_lfs_pointer(self.journey.smartphone_path))

    def test_synchronized_pair_has_equal_rows(self) -> None:
        stats = synchronization_statistics(self.journey)
        self.assertTrue(stats["equal_row_count"])
        self.assertEqual(stats["smartphone_rows"], 51746)
        self.assertEqual(stats["vehicle_rows"], 51746)

    def test_smartphone_schema_and_time(self) -> None:
        frame = self.journey.smartphone
        for field in (
            "gps_latitude_deg",
            "gps_longitude_deg",
            "gps_speed_mps",
            "gps_speed_kmh",
            "accelerometer_x_mps2",
            "gyroscope_z_radps",
            "magnetic_field_x_ut",
            "orientation_azimuth_deg",
            "timestamp_local",
            "elapsed_s",
        ):
            self.assertIn(field, frame.columns)
        stats = sampling_statistics(frame["elapsed_s"])
        self.assertEqual(stats["missing_timestamp_count"], 0)
        self.assertEqual(stats["duplicate_timestamp_count"], 0)
        self.assertEqual(stats["non_monotonic_timestamp_count"], 0)
        self.assertAlmostEqual(stats["approx_frequency_hz"], 10.0, places=6)

    def test_vehicle_schema_and_time(self) -> None:
        frame = self.journey.vehicle
        for field in ("latitude_deg", "longitude_deg", "velocity_kmh", "heading_deg", "elapsed_s"):
            self.assertIn(field, frame.columns)
        stats = sampling_statistics(frame["elapsed_s"])
        self.assertAlmostEqual(stats["approx_frequency_hz"], 10.0, places=5)

    def test_documented_speed_unit_error_is_normalized(self) -> None:
        phone = self.journey.smartphone
        self.assertAlmostEqual(phone["gps_speed_mps"].iloc[0], 5.57, places=6)
        self.assertAlmostEqual(phone["gps_speed_kmh"].iloc[0], 20.052, places=6)
        self.assertAlmostEqual(self.journey.vehicle["velocity_kmh"].iloc[0], 19.969, places=6)


if __name__ == "__main__":
    unittest.main()
