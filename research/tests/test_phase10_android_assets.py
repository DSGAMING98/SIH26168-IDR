from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from idr.ml.velocity_model import load_velocity_bundle
from idr.phase10 import IDR_OUTPUT_COLUMNS, AndroidIdrOutputError, load_android_idr_output


ROOT = Path(__file__).resolve().parents[1]
PARITY = ROOT / "results/phase10/ml_parity_vectors.json"
CHECKPOINT = ROOT / "models/phase5/io_vnbd_s1/velocity_gru.pt"


def _idr_frame() -> pd.DataFrame:
    rows = []
    for index, state in enumerate(("GNSS_ACTIVE", "IDR_ACTIVE", "GNSS_RECOVERING")):
        row = {column: 0.0 for column in IDR_OUTPUT_COLUMNS}
        row.update({
            "sequence_id": index,
            "elapsed_seconds": index * 0.1,
            "monotonic_timestamp_ns": 1_000_000_000 + index * 100_000_000,
            "wall_clock_utc": f"2026-01-01T00:00:0{index}Z",
            "confidence": "HIGH",
            "localization_state": state,
            "alignment_state": "READY",
            "motion_state": "MOVING",
            "ml_state": "ML_ACCEPTED",
            "gnss_acquisition_state": "FRESH",
        })
        rows.append(row)
    return pd.DataFrame(rows, columns=IDR_OUTPUT_COLUMNS)


def test_android_gru_export_matches_frozen_checkpoint_and_python_golden_vectors() -> None:
    payload = json.loads(PARITY.read_text(encoding="utf-8"))
    assert payload["parameter_count"] == 4_257
    assert payload["checkpoint_sha256"] == hashlib.sha256(CHECKPOINT.read_bytes()).hexdigest()
    bundle = load_velocity_bundle(CHECKPOINT)
    for vector in payload["vectors"]:
        residual, ood = bundle.predict_window(np.asarray(vector["raw_feature_window"], dtype=np.float32))
        assert residual == pytest.approx(vector["expected_residual_mps"], abs=1e-7)
        assert ood == pytest.approx(vector["expected_ood_exceedance"], abs=1e-7)


def test_phase10_idr_output_schema_loads_additive_android_stream(tmp_path: Path) -> None:
    frame = _idr_frame()
    frame.to_csv(tmp_path / "idr_output.csv", index=False)
    loaded = load_android_idr_output(tmp_path)
    assert loaded["localization_state"].tolist() == ["GNSS_ACTIVE", "IDR_ACTIVE", "GNSS_RECOVERING"]
    assert tuple(loaded.columns) == IDR_OUTPUT_COLUMNS


def test_phase10_idr_output_rejects_nonmonotonic_time(tmp_path: Path) -> None:
    frame = _idr_frame()
    frame.loc[2, "monotonic_timestamp_ns"] = frame.loc[1, "monotonic_timestamp_ns"]
    frame.to_csv(tmp_path / "idr_output.csv", index=False)
    with pytest.raises(AndroidIdrOutputError, match="monotonic_timestamp_ns"):
        load_android_idr_output(tmp_path)
