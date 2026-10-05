from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from idr.phase8.canonical import (
    CanonicalEvaluationReference,
    CanonicalRuntimeSession,
    create_runtime_blackout,
)


def _runtime() -> CanonicalRuntimeSession:
    elapsed = np.arange(0.1, 2.1, 0.1)
    sensor = pd.DataFrame({"elapsed_s": elapsed, "timestamp_utc_ms": elapsed * 1000})
    for prefix, unit in (("accelerometer", "mps2"), ("gyroscope", "radps"), ("magnetic_field", "ut")):
        for axis in "xyz":
            sensor[f"{prefix}_{axis}_{unit}"] = 1.0
    gnss_elapsed = np.array([0.1, 1.1])
    gnss = pd.DataFrame(
        {
            "elapsed_s": gnss_elapsed,
            "timestamp_utc_ms": gnss_elapsed * 1000,
            "gps_latitude_deg": [10.0, 10.0001],
            "gps_longitude_deg": [20.0, 20.0001],
            "gps_speed_mps": [2.0, 2.0],
            "gps_orientation_deg": [30.0, 30.0],
        }
    )
    return CanonicalRuntimeSession(sensor, gnss, {"session_id": "synthetic"})


def test_canonical_runtime_schema_is_strict_and_normalized() -> None:
    runtime = _runtime()
    assert len(runtime.sensor_data) == 20
    assert runtime.metadata["session_id"] == "synthetic"
    assert runtime.sensor_data["elapsed_s"].is_monotonic_increasing


def test_canonical_runtime_rejects_reference_column() -> None:
    runtime = _runtime()
    sensor = runtime.sensor_data.copy()
    sensor["latitude_deg"] = 10.0
    with pytest.raises(ValueError, match="reference"):
        CanonicalRuntimeSession(sensor, runtime.gnss_data, runtime.metadata)


def test_canonical_reference_is_separate_type() -> None:
    data = pd.DataFrame(
        {
            "elapsed_s": [0.0, 1.0],
            "timestamp_utc_ms": [0, 1000],
            "latitude_deg": [1.0, 1.1],
            "longitude_deg": [2.0, 2.1],
            "speed_mps": [3.0, 4.0],
            "bearing_deg": [5.0, 6.0],
        }
    )
    reference = CanonicalEvaluationReference(data, {"visibility": "evaluation only"})
    assert not isinstance(reference, CanonicalRuntimeSession)


def test_blackout_is_half_open_and_removes_gnss() -> None:
    blackout = create_runtime_blackout(_runtime(), start_s=1.0, duration_s=0.5)
    assert blackout.blackout_sensor_data["elapsed_s"].tolist() == pytest.approx([1.0, 1.1, 1.2, 1.3, 1.4])
    assert not any(column.startswith("gps_") for column in blackout.blackout_sensor_data)
    assert float(blackout.gnss_history["elapsed_s"].max()) < 1.0


def test_blackout_rejects_invalid_ranges() -> None:
    runtime = _runtime()
    with pytest.raises(ValueError):
        create_runtime_blackout(runtime, start_s=1.0, duration_s=0.0)
    with pytest.raises(ValueError):
        create_runtime_blackout(runtime, start_s=1.8, duration_s=1.0)


def test_blackout_is_deterministic() -> None:
    runtime = _runtime()
    first = create_runtime_blackout(runtime, start_s=1.0, duration_s=0.5)
    second = create_runtime_blackout(runtime, start_s=1.0, duration_s=0.5)
    pd.testing.assert_frame_equal(first.blackout_sensor_data, second.blackout_sensor_data)
