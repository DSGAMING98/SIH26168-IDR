from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pandas as pd
import pytest

from idr.phase9 import AndroidSessionError, CausalLatestBuffer, load_android_session
from idr.phase9.schema import GNSS_DIAGNOSTIC_FIELDS, GNSS_SENSITIVE_FIELDS, SENSOR_UNITS


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase9_android_session"


def _copy_fixture(tmp_path: Path) -> Path:
    destination = tmp_path / "session"
    shutil.copytree(FIXTURE, destination)
    return destination


def _rewrite_csv(path: Path, transform) -> None:
    frame = pd.read_csv(path)
    transform(frame)
    frame.to_csv(path, index=False)


def test_android_session_loader_parses_metadata_and_all_streams() -> None:
    session = load_android_session(FIXTURE)
    assert session.session_id == "synthetic_phase9_android_session"
    assert len(session.runtime) == 40
    assert len(session.raw_imu) == 1_000
    assert len(session.raw_physical_gnss) == 5
    assert session.metadata["device_model"] == "FixturePhone"


def test_phase91_gnss_observability_and_first_fix_metadata() -> None:
    session = load_android_session(FIXTURE)
    diagnostics = session.metadata["gnss_diagnostics"]
    final = session.runtime.iloc[-1]
    assert diagnostics["physical_callback_count"] == 5
    assert diagnostics["first_valid_fix_timestamp_ns"] == 1_000_000_000_000
    assert diagnostics["time_to_first_fix_seconds"] == 0.0
    assert final["physical_gnss_callback_count"] == 5
    assert final["satellites_visible"] == 12
    assert final["satellites_used_in_fix"] == 6
    assert final["gnss_status_available"]


def test_blackout_cannot_claim_real_masking_without_first_fix(tmp_path: Path) -> None:
    directory = _copy_fixture(tmp_path)
    metadata = json.loads((directory / "session_metadata.json").read_text())
    metadata["gnss_diagnostics"]["first_valid_fix_timestamp_ns"] = None
    metadata["gnss_diagnostics"]["time_to_first_fix_seconds"] = None
    (directory / "session_metadata.json").write_text(json.dumps(metadata))
    def erase_first_fix(frame: pd.DataFrame) -> None:
        frame["first_valid_gnss_fix_timestamp_ns"] = pd.Series(float("nan"), index=frame.index, dtype=float)
        frame["time_to_first_fix_seconds"] = pd.Series(float("nan"), index=frame.index, dtype=float)
    _rewrite_csv(directory / "runtime_10hz.csv", erase_first_fix)
    with pytest.raises(AndroidSessionError, match="blackout_masks_real_fix"):
        load_android_session(directory)


def test_satellite_counts_remain_unavailable_instead_of_fabricated(tmp_path: Path) -> None:
    directory = _copy_fixture(tmp_path)
    metadata = json.loads((directory / "session_metadata.json").read_text())
    metadata["gnss_diagnostics"]["gnss_status_available"] = False
    metadata["gnss_diagnostics"]["satellites_visible"] = None
    metadata["gnss_diagnostics"]["satellites_used_in_fix"] = None
    (directory / "session_metadata.json").write_text(json.dumps(metadata))
    def remove_satellites(frame: pd.DataFrame) -> None:
        frame.loc[:, "gnss_status_available"] = False
        frame["satellites_visible"] = pd.Series(float("nan"), index=frame.index, dtype=float)
        frame["satellites_used_in_fix"] = pd.Series(float("nan"), index=frame.index, dtype=float)
    _rewrite_csv(directory / "runtime_10hz.csv", remove_satellites)
    session = load_android_session(directory)
    assert not session.runtime["gnss_status_available"].any()
    assert session.runtime[["satellites_visible", "satellites_used_in_fix"]].isna().all(axis=None)


def test_phase9_schema_v1_recording_remains_loadable(tmp_path: Path) -> None:
    directory = _copy_fixture(tmp_path)
    metadata = json.loads((directory / "session_metadata.json").read_text())
    metadata["schema_version"] = 1
    metadata.pop("gnss_diagnostics")
    (directory / "session_metadata.json").write_text(json.dumps(metadata))
    def downgrade(frame: pd.DataFrame) -> None:
        frame.drop(columns=list(GNSS_DIAGNOSTIC_FIELDS), inplace=True)
        frame.loc[frame["gnss_status"] == "WAITING_FOR_FIRST_FIX", "gnss_status"] = "NO_FIX"
    _rewrite_csv(directory / "runtime_10hz.csv", downgrade)
    session = load_android_session(directory)
    assert set(GNSS_DIAGNOSTIC_FIELDS).issubset(session.runtime.columns)
    assert session.runtime["physical_gnss_callback_count"].iloc[-1] == 5
    assert not session.runtime["gnss_status_available"].any()


def test_phase9_schema_v1_zero_fix_phone_recording_stays_waiting(tmp_path: Path) -> None:
    directory = _copy_fixture(tmp_path)
    metadata = json.loads((directory / "session_metadata.json").read_text())
    metadata["schema_version"] = 1
    metadata.pop("gnss_diagnostics")
    (directory / "session_metadata.json").write_text(json.dumps(metadata))

    def remove_all_gnss(frame: pd.DataFrame) -> None:
        frame.drop(columns=list(GNSS_DIAGNOSTIC_FIELDS), inplace=True)
        frame.loc[:, list(GNSS_SENSITIVE_FIELDS)] = float("nan")
        frame.loc[:, "gnss_is_fresh"] = False
        frame.loc[~frame["simulated_blackout"], "gnss_status"] = "NO_FIX"

    _rewrite_csv(directory / "runtime_10hz.csv", remove_all_gnss)
    _rewrite_csv(directory / "gnss_raw.csv", lambda frame: frame.drop(frame.index, inplace=True))
    session = load_android_session(directory)
    visible = session.runtime.loc[~session.runtime["simulated_blackout"]]
    assert set(visible["gnss_status"]) == {"WAITING_FOR_FIRST_FIX"}
    assert session.runtime["physical_gnss_callback_count"].eq(0).all()
    assert not session.runtime["blackout_masks_real_fix"].any()


def test_schema_validation_rejects_missing_runtime_column(tmp_path: Path) -> None:
    directory = _copy_fixture(tmp_path)
    _rewrite_csv(directory / "runtime_10hz.csv", lambda frame: frame.drop(columns=["gyroscope_z_radps"], inplace=True))
    with pytest.raises(AndroidSessionError, match="schema mismatch"):
        load_android_session(directory)


def test_runtime_requires_strict_monotonic_timestamps(tmp_path: Path) -> None:
    directory = _copy_fixture(tmp_path)
    def break_order(frame: pd.DataFrame) -> None:
        frame.loc[10, "monotonic_timestamp_ns"] = frame.loc[9, "monotonic_timestamp_ns"]
    _rewrite_csv(directory / "runtime_10hz.csv", break_order)
    with pytest.raises(AndroidSessionError, match="monotonic_timestamp_ns"):
        load_android_session(directory)


def test_raw_stream_rejects_out_of_order_samples(tmp_path: Path) -> None:
    directory = _copy_fixture(tmp_path)
    def break_order(frame: pd.DataFrame) -> None:
        rows = frame.index[frame["sensor_type"] == "accelerometer"]
        frame.loc[rows[2], "event_timestamp_ns"] = frame.loc[rows[1], "event_timestamp_ns"] - 1
    _rewrite_csv(directory / "imu_raw.csv", break_order)
    with pytest.raises(AndroidSessionError, match="raw accelerometer"):
        load_android_session(directory)


def test_causal_snapshot_never_reads_future_sample() -> None:
    buffer = CausalLatestBuffer()
    buffer.add("accelerometer", 100, "past")
    buffer.add("accelerometer", 300, "future")
    assert buffer.latest_at_or_before("accelerometer", 200).value == "past"
    assert buffer.latest_at_or_before("accelerometer", 99) is None


def test_causal_buffer_rejects_duplicate_and_out_of_order_input() -> None:
    buffer = CausalLatestBuffer()
    buffer.add("gyro", 100, 1)
    with pytest.raises(ValueError, match="Out-of-order"):
        buffer.add("gyro", 100, 2)
    with pytest.raises(ValueError, match="Out-of-order"):
        buffer.add("gyro", 99, 3)


def test_fixture_contains_fresh_stale_blackout_and_return() -> None:
    runtime = load_android_session(FIXTURE).runtime
    assert runtime["gnss_status"].tolist()[:10] == ["FRESH"] * 10
    assert runtime["gnss_status"].tolist()[10:15] == ["STALE"] * 5
    assert runtime["gnss_status"].tolist()[15:25] == ["SIMULATED_BLACKOUT"] * 10
    assert runtime["gnss_status"].tolist()[25:] == ["FRESH"] * 15


def test_explicit_no_runtime_gnss_leakage_during_blackout() -> None:
    runtime = load_android_session(FIXTURE).runtime
    blackout = runtime[runtime["simulated_blackout"]]
    assert len(blackout) == 10
    assert blackout.loc[:, list(GNSS_SENSITIVE_FIELDS)].isna().all(axis=None)
    assert not blackout["gnss_is_fresh"].any()


def test_loader_rejects_blackout_gnss_leakage(tmp_path: Path) -> None:
    directory = _copy_fixture(tmp_path)
    def leak(frame: pd.DataFrame) -> None:
        frame.loc[frame["simulated_blackout"], "gnss_speed_mps"] = 5.0
    _rewrite_csv(directory / "runtime_10hz.csv", leak)
    with pytest.raises(AndroidSessionError, match="GNSS leakage"):
        load_android_session(directory)


def test_raw_physical_gnss_is_retained_but_marked_masked() -> None:
    session = load_android_session(FIXTURE)
    masked = session.raw_physical_gnss[session.raw_physical_gnss["masked_from_runtime"]]
    assert masked["elapsed_seconds"].tolist() == pytest.approx([2.0])
    assert session.runtime.loc[session.runtime["simulated_blackout"], "gnss_latitude_deg"].isna().all()


def test_missing_magnetometer_is_explicit_and_core_adapter_rejects(tmp_path: Path) -> None:
    directory = _copy_fixture(tmp_path)
    metadata = json.loads((directory / "session_metadata.json").read_text())
    metadata["availability"]["magnetometer"] = False
    (directory / "session_metadata.json").write_text(json.dumps(metadata))
    def remove_magnetometer(frame: pd.DataFrame) -> None:
        frame.loc[:, "magnetometer_available"] = False
        frame.loc[:, [f"magnetometer_{axis}_ut" for axis in "xyz"]] = float("nan")
    _rewrite_csv(directory / "runtime_10hz.csv", remove_magnetometer)
    _rewrite_csv(directory / "imu_raw.csv", lambda frame: frame.drop(frame[frame["sensor_type"] == "magnetometer"].index, inplace=True))
    session = load_android_session(directory)
    assert "magnetometer" in session.missing_sensors
    with pytest.raises(AndroidSessionError, match="Core estimator sensors unavailable"):
        session.to_canonical_runtime()


def test_missing_gravity_is_explicit_but_core_adapter_remains_usable(tmp_path: Path) -> None:
    directory = _copy_fixture(tmp_path)
    metadata = json.loads((directory / "session_metadata.json").read_text())
    metadata["availability"]["gravity"] = False
    (directory / "session_metadata.json").write_text(json.dumps(metadata))
    def remove_gravity(frame: pd.DataFrame) -> None:
        frame.loc[:, "gravity_available"] = False
        frame.loc[:, [f"gravity_{axis}_mps2" for axis in "xyz"]] = float("nan")
    _rewrite_csv(directory / "runtime_10hz.csv", remove_gravity)
    _rewrite_csv(directory / "imu_raw.csv", lambda frame: frame.drop(frame[frame["sensor_type"] == "gravity"].index, inplace=True))
    session = load_android_session(directory)
    canonical = session.to_canonical_runtime()
    assert "gravity" in session.missing_sensors
    assert "gravity_x_mps2" not in canonical.sensor_data


def test_unit_contract_is_exact_and_wrong_units_fail(tmp_path: Path) -> None:
    assert load_android_session(FIXTURE).metadata["units"] == SENSOR_UNITS
    directory = _copy_fixture(tmp_path)
    metadata = json.loads((directory / "session_metadata.json").read_text())
    metadata["units"]["gyroscope"] = "degrees/s"
    (directory / "session_metadata.json").write_text(json.dumps(metadata))
    with pytest.raises(AndroidSessionError, match="units"):
        load_android_session(directory)


def test_achieved_sample_rate_uses_timestamps() -> None:
    rates = load_android_session(FIXTURE).achieved_rates_hz()
    assert rates["accelerometer"] == pytest.approx(50.0)
    assert rates["gyroscope"] == pytest.approx(50.0)
    assert rates["normalized"] == pytest.approx(10.0)


def test_canonical_adapter_contains_runtime_only_data() -> None:
    canonical = load_android_session(FIXTURE).to_canonical_runtime()
    assert "magnetic_field_x_ut" in canonical.sensor_data
    assert "gnss_status" not in canonical.sensor_data
    assert "latitude_deg" not in canonical.sensor_data
    assert canonical.metadata["source"] == "android_phase9_runtime_only"
    assert float(canonical.gnss_data["elapsed_s"].min()) == 0.0


@pytest.mark.parametrize(
    ("relative_path", "expected"),
    [
        ("models/phase5/io_vnbd_s1/velocity_gru.pt", "fa2169781f9e499dd87fdd00038a3b4a1326181b31938cec237a7802ae0bb4ec"),
        ("configs/phase6/io_vnbd_s1_phase6.json", "a1fa39c0aff3170ac68874bd05b1ef059bb0596525dffd0a0c8ebc69f406d952"),
        ("configs/phase7/io_vnbd_s1_phase7.json", "bfcb4ebc22f8eaa1d625b35eba0c359b878c0f75f39ce8249c1d716a87d0354e"),
    ],
)
def test_phase9_preserves_frozen_phase5_phase6_phase7(relative_path: str, expected: str) -> None:
    assert hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest() == expected


def test_committed_fixture_is_declared_synthetic() -> None:
    metadata = load_android_session(FIXTURE).metadata
    assert metadata["device_manufacturer"] == "Synthetic"
    assert metadata["fixture_notice"].startswith("SYNTHETIC ONLY")
