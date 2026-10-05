from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from idr.phase8.adapters.smartphone_decimeter import (
    SmartphoneDecimeterAdapter,
    _read_sensor,
    ecef_to_wgs84,
)


def _write_imu(path: Path, *, omit: str | None = None) -> None:
    rows = []
    values = {
        "UncalAccel": (0.0, 0.0, 9.80665),
        "UncalGyro": (0.0, 0.0, 0.01),
        "UncalMag": (20.0, 40.0, 0.0),
    }
    for time_ms in (1, 50, 100, 101, 150, 200):
        for message, value in values.items():
            if message == omit:
                continue
            rows.append([message, time_ms, *value, 0.0, 0.0, 0.0])
    pd.DataFrame(
        rows,
        columns=["MessageType", "utcTimeMillis", "MeasurementX", "MeasurementY", "MeasurementZ", "BiasX", "BiasY", "BiasZ"],
    ).to_csv(path / "device_imu.csv", index=False)


def _write_gnss(path: Path) -> None:
    pd.DataFrame(
        {
            "utcTimeMillis": [0, 1000],
            "WlsPositionXEcefMeters": [6378137.0, 6378137.0],
            "WlsPositionYEcefMeters": [0.0, 1.0],
            "WlsPositionZEcefMeters": [0.0, 0.0],
        }
    ).to_csv(path / "device_gnss.csv", index=False)


def test_ecef_unit_conversion_known_equator_point() -> None:
    latitude, longitude = ecef_to_wgs84(np.array([6378137.0]), np.array([0.0]), np.array([0.0]))
    assert latitude[0] == pytest.approx(0.0, abs=1e-10)
    assert longitude[0] == pytest.approx(0.0, abs=1e-10)


def test_right_closed_resampling_is_causal(tmp_path: Path) -> None:
    _write_imu(tmp_path)
    result = _read_sensor(tmp_path / "device_imu.csv", "UncalAccel", 0, 100)
    # t=100 belongs to the bin ending at 100; t=101 belongs to the next bin.
    assert result["bin"].tolist() == [1, 2]
    assert len(result) == 2


def test_uncalibrated_bias_is_subtracted(tmp_path: Path) -> None:
    pd.DataFrame(
        [["UncalAccel", 10, 5.0, 6.0, 7.0, 1.0, 2.0, 3.0]],
        columns=["MessageType", "utcTimeMillis", "MeasurementX", "MeasurementY", "MeasurementZ", "BiasX", "BiasY", "BiasZ"],
    ).to_csv(tmp_path / "device_imu.csv", index=False)
    result = _read_sensor(tmp_path / "device_imu.csv", "UncalAccel", 0, 100)
    assert result.loc[0, ["x", "y", "z"]].tolist() == pytest.approx([4.0, 4.0, 4.0])


def test_different_native_rates_have_same_effective_bins(tmp_path: Path) -> None:
    for name, step in (("slow", 50), ("fast", 10)):
        directory = tmp_path / name
        directory.mkdir()
        times = np.arange(step, 401, step)
        pd.DataFrame(
            [["UncalAccel", int(t), float(t // 100), 0.0, 0.0, 0.0, 0.0, 0.0] for t in times],
            columns=["MessageType", "utcTimeMillis", "MeasurementX", "MeasurementY", "MeasurementZ", "BiasX", "BiasY", "BiasZ"],
        ).to_csv(directory / "device_imu.csv", index=False)
    slow = _read_sensor(tmp_path / "slow/device_imu.csv", "UncalAccel", 0, 100)
    fast = _read_sensor(tmp_path / "fast/device_imu.csv", "UncalAccel", 0, 100)
    assert slow["bin"].tolist() == fast["bin"].tolist() == [1, 2, 3, 4]


def test_missing_required_sensor_fails_clearly(tmp_path: Path) -> None:
    _write_imu(tmp_path, omit="UncalMag")
    _write_gnss(tmp_path)
    with pytest.raises(ValueError, match="UncalMag"):
        SmartphoneDecimeterAdapter(tmp_path, "missing").load_runtime()


def test_runtime_loader_does_not_require_or_read_ground_truth(tmp_path: Path) -> None:
    _write_imu(tmp_path)
    _write_gnss(tmp_path)
    runtime = SmartphoneDecimeterAdapter(tmp_path, "isolated").load_runtime()
    assert len(runtime.sensor_data) == 2
    assert not (tmp_path / "ground_truth.csv").exists()


def test_adapter_is_deterministic(tmp_path: Path) -> None:
    _write_imu(tmp_path)
    _write_gnss(tmp_path)
    adapter = SmartphoneDecimeterAdapter(tmp_path, "repeat")
    first = adapter.load_runtime()
    second = adapter.load_runtime()
    pd.testing.assert_frame_equal(first.sensor_data, second.sensor_data)
    pd.testing.assert_frame_equal(first.gnss_data, second.gnss_data)
