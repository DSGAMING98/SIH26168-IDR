from __future__ import annotations

import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd
import pytest

from idr.phase10.android_idr import IDR_OUTPUT_COLUMNS
from idr.phase11.session_validation import load_evaluation_reference, validate_android_session


FIXTURE = Path(__file__).parent / "fixtures" / "phase9_android_session"


def _session(tmp_path: Path) -> Path:
    root = tmp_path / "private_phone_export"
    shutil.copytree(FIXTURE, root)
    runtime = pd.read_csv(root / "runtime_10hz.csv")
    raw = pd.read_csv(root / "gnss_raw.csv")
    t = runtime["elapsed_seconds"].to_numpy(float)
    ref_t = raw["elapsed_seconds"].to_numpy(float)
    lat = np.interp(t, ref_t, raw["latitude_deg"])
    lon = np.interp(t, ref_t, raw["longitude_deg"])
    blackout = runtime["simulated_blackout"].astype(str).str.lower().eq("true").to_numpy()
    lon = lon + blackout * 0.00001
    origin_lat, origin_lon = lat[0], lon[0]
    east = (lon - origin_lon) * 111_000.0 * np.cos(np.radians(origin_lat))
    north = (lat - origin_lat) * 111_000.0
    states = np.where(blackout, "IDR_ACTIVE", "GNSS_ACTIVE")
    idr = pd.DataFrame({
        "sequence_id": runtime["sequence_id"],
        "elapsed_seconds": runtime["elapsed_seconds"],
        "monotonic_timestamp_ns": runtime["monotonic_timestamp_ns"],
        "wall_clock_utc": runtime["wall_clock_utc"],
        "local_east_m": east,
        "local_north_m": north,
        "estimated_latitude_deg": lat,
        "estimated_longitude_deg": lon,
        "estimated_speed_mps": 5.0,
        "estimated_heading_deg": 45.0,
        "horizontal_uncertainty_m": np.where(blackout, 4.0, 2.0),
        "confidence": np.where(blackout, "MEDIUM", "HIGH"),
        "localization_state": states,
        "alignment_state": "READY",
        "motion_state": "MOVING",
        "ml_state": np.where(blackout, "ML_OOD_LIMITED", "ML_ACCEPTED"),
        "ml_residual_mps": np.where(blackout, 0.05, 0.0),
        "ml_ood_exceedance": np.where(blackout, 0.2, 0.0),
        "dr_duration_seconds": np.where(blackout, t - t[blackout][0], 0.0),
        "gnss_innovation_m": np.nan,
        "last_correction_m": np.where(blackout, 0.0, 0.1),
        "engine_average_ms": 0.2,
        "engine_p95_ms": 0.3,
        "gnss_acquisition_state": runtime["gnss_status"],
    })
    idr.loc[:, IDR_OUTPUT_COLUMNS].to_csv(root / "idr_output.csv", index=False)
    return root


def test_validator_computes_blackout_metrics_and_writes_beside_session(tmp_path: Path) -> None:
    root = _session(tmp_path)
    result = validate_android_session(root)

    assert result.evaluable
    assert result.output_directory == root / "phase11_validation"
    assert len(result.blackout_metrics) == 1
    metric = result.blackout_metrics[0]
    assert metric["blackout_duration_seconds"] == pytest.approx(0.9)
    assert metric["final_position_error_m"] > 0
    assert metric["rmse_position_error_m"] > 0
    assert metric["reference_distance_m"] > 0
    assert metric["ml_state_fractions"]["ML_OOD_LIMITED"] == 1.0
    assert (root / "phase11_validation" / "phase11_validation.json").is_file()
    assert (root / "phase11_validation" / "PHASE11_FIELD_REPORT.md").is_file()
    payload = json.loads((root / "phase11_validation" / "phase11_validation.json").read_text())
    assert "survey-grade" in payload["limitations"][0]


def test_reference_quality_gate_reports_missing_and_rejected_values(tmp_path: Path) -> None:
    root = _session(tmp_path)
    external = tmp_path / "reference.csv"
    pd.DataFrame({
        "elapsed_seconds": [0.0, 1.0, 2.0, 3.0, 4.0],
        "latitude_deg": [12.0, 12.0001, 120.0, 12.0003, 12.0004],
        "longitude_deg": [77.0, 77.0001, 77.0002, 77.0003, 77.0004],
        "accuracy_m": [np.nan, 4.0, 4.0, 99.0, 4.0],
        "speed_mps": [1.0, 1.0, 1.0, 1.0, 100.0],
    }).to_csv(external, index=False)

    retained, quality, audit = load_evaluation_reference(root, external)
    assert len(retained) == 2
    assert quality.rejected_points == 3
    assert quality.rejection_reasons == {
        "implausible_speed": 1,
        "invalid_coordinate": 1,
        "poor_horizontal_accuracy": 1,
    }
    assert audit.loc[0, "retained"]


def test_validator_can_run_without_writing_or_copying_private_data(tmp_path: Path) -> None:
    root = _session(tmp_path)
    result = validate_android_session(root, write_outputs=False)

    assert result.evaluable
    assert result.output_directory is None
    assert not (root / "phase11_validation").exists()


def test_pre_phase10_session_is_classified_not_evaluable_without_false_accuracy_claim(tmp_path: Path) -> None:
    root = tmp_path / "old_phone_export"
    shutil.copytree(FIXTURE, root)
    result = validate_android_session(root, write_outputs=False)
    assert not result.evaluable
    assert result.blackout_metrics == ()
    assert any("lacks Phase 10/11 estimator output" in text for text in result.limitations)


def test_optional_gpx_reference_is_supported_without_extra_dependency(tmp_path: Path) -> None:
    root = _session(tmp_path)
    gpx = tmp_path / "independent.gpx"
    gpx.write_text(
        """<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>
<trkpt lat="12.0" lon="77.0"><time>2026-01-01T00:00:00Z</time></trkpt>
<trkpt lat="12.0001" lon="77.0001"><time>2026-01-01T00:00:01Z</time></trkpt>
</trkseg></trk></gpx>""",
        encoding="utf-8",
    )
    retained, quality, _ = load_evaluation_reference(root, gpx)
    assert len(retained) == 2
    assert quality.source == "independent evaluation reference (gpx)"
