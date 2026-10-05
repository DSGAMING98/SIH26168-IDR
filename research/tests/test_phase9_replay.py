from __future__ import annotations

from pathlib import Path

from idr.phase9 import load_android_session, replay_session


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase9_android_session"


def test_replay_is_chronological() -> None:
    seen: list[int] = []
    replay_session(load_android_session(FIXTURE), lambda row: seen.append(int(row["monotonic_timestamp_ns"])))
    assert len(seen) == 40
    assert all(current < following for current, following in zip(seen, seen[1:]))


def test_replay_is_deterministic_except_wall_runtime_measurement() -> None:
    session = load_android_session(FIXTURE)
    first = replay_session(session).to_dict()
    second = replay_session(session).to_dict()
    first.pop("replay_throughput_samples_per_s")
    second.pop("replay_throughput_samples_per_s")
    assert first == second


def test_replay_preserves_blackout_and_health_telemetry() -> None:
    result = replay_session(load_android_session(FIXTURE))
    assert result.blackout_samples == 10
    assert result.gnss_status_counts == {"FRESH": 25, "SIMULATED_BLACKOUT": 10, "STALE": 5}
    assert result.ml_ood_state_counts == {"NOT_EVALUATED": 40}
    assert result.missing_sensors == ()


def test_replay_consumer_never_receives_raw_physical_gnss_fields() -> None:
    rows: list[dict[str, object]] = []
    replay_session(load_android_session(FIXTURE), rows.append)
    assert all("latitude_deg" not in row and "masked_from_runtime" not in row for row in rows)
    blackout = [row for row in rows if row["simulated_blackout"]]
    assert all(row["gnss_latitude_deg"] != row["gnss_latitude_deg"] for row in blackout)  # NaN


def test_replay_normalized_stream_meets_ten_hz_target() -> None:
    result = replay_session(load_android_session(FIXTURE))
    assert result.normalized_rate_hz == 10.0
    assert result.replay_throughput_samples_per_s > 10.0
