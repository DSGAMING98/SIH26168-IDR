from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import torch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from idr.ml.features import (  # noqa: E402
    FEATURE_ORDER,
    build_runtime_feature_frame,
    make_causal_windows,
    verify_split_manifest,
)
from idr.ml.velocity_model import (  # noqa: E402
    FeatureScaler,
    VelocityGRU,
    VelocityModelConfig,
    fit_feature_scaler,
    load_velocity_bundle,
    save_velocity_bundle,
)


def _features(count: int = 10, offset: float = 0.0) -> pd.DataFrame:
    values = np.arange(count * len(FEATURE_ORDER), dtype=float).reshape(count, -1) + offset
    return pd.DataFrame(values, columns=list(FEATURE_ORDER))


def _config(window: int = 4) -> VelocityModelConfig:
    return VelocityModelConfig(len(FEATURE_ORDER), 8, 1, 12.0, window, 10.0, 1, 26168)


class CausalFeatureTests(unittest.TestCase):
    def test_window_creation_is_causal(self) -> None:
        batch = make_causal_windows(_features(6), np.arange(6), window_steps=3)
        np.testing.assert_array_equal(batch.end_indices, [2, 3, 4, 5])
        np.testing.assert_array_equal(batch.inputs[0], _features(6).to_numpy()[:3])
        np.testing.assert_array_equal(batch.targets, [2, 3, 4, 5])

    def test_future_sample_does_not_change_past_window(self) -> None:
        original = _features(6)
        changed = original.copy()
        changed.iloc[-1] = 1e9
        first = make_causal_windows(original, None, window_steps=3)
        second = make_causal_windows(changed, None, window_steps=3)
        np.testing.assert_array_equal(first.inputs[:-1], second.inputs[:-1])

    def test_split_boundaries_prevent_overlap(self) -> None:
        manifest = {
            "training_intervals": [{"start_s": 0, "end_s": 10}],
            "validation_intervals": [{"start_s": 9, "end_s": 20}],
            "quarantine_intervals": [],
        }
        with self.assertRaisesRegex(ValueError, "overlapping"):
            verify_split_manifest(manifest)

    def test_benchmark_quarantine_is_disjoint(self) -> None:
        manifest = json.loads(
            (ROOT / "configs" / "phase5" / "io_vnbd_s1_split.json").read_text(encoding="utf-8")
        )
        checks = verify_split_manifest(manifest)
        self.assertTrue(checks["benchmark_quarantine_disjoint"])
        self.assertEqual(checks["quarantine_interval_count"], 6)

    def test_scaler_uses_training_rows_only(self) -> None:
        training = _features(5)
        scaler = fit_feature_scaler([training])
        validation = _features(5, 100000.0)
        scaler.transform(validation.to_numpy())
        np.testing.assert_allclose(scaler.means, training.mean().to_numpy())

    def test_feature_order_is_deterministic_and_has_no_route_identifiers(self) -> None:
        self.assertEqual(tuple(_features().columns), FEATURE_ORDER)
        forbidden = {"scenario_id", "elapsed_s", "latitude_deg", "longitude_deg", "VBOX"}
        self.assertFalse(forbidden.intersection(FEATURE_ORDER))

    def test_vbox_field_rejected_from_runtime_features(self) -> None:
        sensor = pd.DataFrame({"elapsed_s": [0.1], "latitude_deg": [52.0]})
        with self.assertRaisesRegex(ValueError, "forbidden"):
            build_runtime_feature_frame(sensor, pd.DataFrame(), np.zeros(1))


class VelocityModelTests(unittest.TestCase):
    def test_model_output_shape_and_finiteness(self) -> None:
        model = VelocityGRU(_config())
        output = model(torch.zeros((3, 4, len(FEATURE_ORDER))))
        self.assertEqual(tuple(output.shape), (3,))
        self.assertTrue(torch.isfinite(output).all())

    def test_same_input_produces_same_prediction(self) -> None:
        torch.manual_seed(1)
        model = VelocityGRU(_config()).eval()
        inputs = torch.ones((1, 4, len(FEATURE_ORDER)))
        with torch.inference_mode():
            first = model(inputs).clone()
            second = model(inputs).clone()
        torch.testing.assert_close(first, second, rtol=0.0, atol=0.0)

    def test_checkpoint_save_load_equality(self) -> None:
        config = _config()
        torch.manual_seed(2)
        model = VelocityGRU(config).eval()
        scaler = FeatureScaler(FEATURE_ORDER, (0.0,) * 10, (1.0,) * 10, (-2.0,) * 10, (2.0,) * 10)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.pt"
            save_velocity_bundle(path, model, scaler, config, 1.0, {"ok": True})
            loaded = load_velocity_bundle(path)
            values = np.ones((4, 10), dtype=np.float32)
            self.assertEqual(loaded.predict_window(values), load_velocity_bundle(path).predict_window(values))

    def test_final_checkpoint_inference_without_vbox(self) -> None:
        checkpoint = ROOT / "models" / "phase5" / "io_vnbd_s1" / "velocity_gru.pt"
        bundle = load_velocity_bundle(checkpoint)
        residual, ood = bundle.predict_window(np.zeros((bundle.config.window_steps, len(FEATURE_ORDER))))
        self.assertTrue(np.isfinite([residual, ood]).all())
        self.assertLess(sum(parameter.numel() for parameter in bundle.model.parameters()), 500000)


if __name__ == "__main__":
    unittest.main()
