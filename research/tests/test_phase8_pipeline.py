from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from idr.phase8.capability import require_core_compatible
from idr.phase8.pipeline import adapt_runtime_sensor_frame, estimate_mounting_forward_axis


ROOT = Path(__file__).resolve().parents[1]


def _sensor(sample_rate_hz: float = 10.0, duration_s: float = 5.0) -> pd.DataFrame:
    elapsed = np.arange(1.0 / sample_rate_hz, duration_s + 1e-9, 1.0 / sample_rate_hz)
    return pd.DataFrame(
        {
            "elapsed_s": elapsed,
            "timestamp_utc_ms": elapsed * 1000.0,
            "accelerometer_x_mps2": 0.2 * np.sin(elapsed),
            "accelerometer_y_mps2": 0.1 * np.cos(elapsed),
            "accelerometer_z_mps2": np.full(len(elapsed), 9.80665),
            "gyroscope_x_radps": np.zeros(len(elapsed)),
            "gyroscope_y_radps": np.zeros(len(elapsed)),
            "gyroscope_z_radps": np.full(len(elapsed), 0.01),
            "magnetic_field_x_ut": np.full(len(elapsed), 20.0),
            "magnetic_field_y_ut": np.full(len(elapsed), 40.0),
            "magnetic_field_z_ut": np.zeros(len(elapsed)),
        }
    )


def test_frame_transform_produces_level_vehicle_frame() -> None:
    adapted = adapt_runtime_sensor_frame(_sensor(), forward_axis_device=np.array([1.0, 0.0, 0.0]))
    assert np.allclose(adapted[["gravity_x_mps2", "gravity_y_mps2"]], 0.0)
    assert np.allclose(adapted["gravity_z_mps2"], 9.80665)
    assert np.all(np.isfinite(adapted.select_dtypes(include=[np.number])))


def test_no_future_sample_leakage_in_causal_adaptation() -> None:
    source = _sensor(duration_s=6.0)
    altered = source.copy()
    altered.loc[altered["elapsed_s"] > 3.0, "accelerometer_x_mps2"] = 5.0
    first = adapt_runtime_sensor_frame(source, forward_axis_device=np.array([1.0, 0.0, 0.0]))
    second = adapt_runtime_sensor_frame(altered, forward_axis_device=np.array([1.0, 0.0, 0.0]))
    pd.testing.assert_frame_equal(first.loc[first["elapsed_s"] <= 3.0], second.loc[second["elapsed_s"] <= 3.0])


def test_mounting_axis_is_deterministic_and_horizontal() -> None:
    source = _sensor(duration_s=70.0)
    first = estimate_mounting_forward_axis(source)
    second = estimate_mounting_forward_axis(source)
    assert first == pytest.approx(second)
    assert np.linalg.norm(first) == pytest.approx(1.0)
    assert abs(first[2]) < 0.1


def test_unsupported_dataset_fails_instead_of_fabricating() -> None:
    with pytest.raises(ValueError, match="not core Phase 5 compatible"):
        require_core_compatible("MoRPI")


@pytest.mark.parametrize(
    ("relative_path", "expected"),
    [
        ("models/phase5/io_vnbd_s1/velocity_gru.pt", "fa2169781f9e499dd87fdd00038a3b4a1326181b31938cec237a7802ae0bb4ec"),
        ("models/phase5/io_vnbd_s1/feature_scaler.json", "5ddea9cf91db0071528b56fc1d303edd0850769efdd53f77c03b0feba9cbf36a"),
        ("configs/phase6/io_vnbd_s1_phase6.json", "a1fa39c0aff3170ac68874bd05b1ef059bb0596525dffd0a0c8ebc69f406d952"),
        ("configs/phase7/io_vnbd_s1_phase7.json", "bfcb4ebc22f8eaa1d625b35eba0c359b878c0f75f39ce8249c1d716a87d0354e"),
    ],
)
def test_frozen_artifact_hashes_unchanged(relative_path: str, expected: str) -> None:
    assert hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest() == expected


def test_phase8_config_is_frozen_zero_shot() -> None:
    text = (ROOT / "configs/phase8/cross_dataset_zero_shot.json").read_text(encoding="utf-8")
    assert '"status": "frozen_before_reference_evaluation"' in text
    assert '"protocol": "zero_shot_no_target_training"' in text


def test_consumed_source_files_match_integrity_manifest() -> None:
    import json

    manifest_path = ROOT / "results/phase8/integrity_manifest.json"
    if not manifest_path.exists():
        pytest.skip("Phase 8 result generation has not run in this checkout.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for relative_path, record in manifest["consumed_source_files"].items():
        assert hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest() == record["sha256_before"]
        assert record["unchanged"] is True
