"""Deterministic, no-sleep desktop replay of runtime-safe Android samples."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Callable, Mapping, Any

from idr.phase9.android_session import AndroidSession


@dataclass(frozen=True)
class ReplayResult:
    session_id: str
    sample_count: int
    recording_duration_s: float
    normalized_rate_hz: float
    replay_throughput_samples_per_s: float
    blackout_samples: int
    gnss_status_counts: Mapping[str, int]
    missing_sensors: tuple[str, ...]
    ml_ood_state_counts: Mapping[str, int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def replay_session(
    session: AndroidSession,
    consumer: Callable[[dict[str, Any]], None] | None = None,
) -> ReplayResult:
    """Feed normalized snapshots in recorded order with no future data or raw GNSS."""

    callback = consumer or (lambda _: None)
    start = perf_counter()
    statuses: Counter[str] = Counter()
    ood_states: Counter[str] = Counter()
    blackout_samples = 0
    previous_ns: int | None = None
    for record in session.runtime.to_dict(orient="records"):
        timestamp_ns = int(record["monotonic_timestamp_ns"])
        if previous_ns is not None and timestamp_ns <= previous_ns:
            raise RuntimeError("Replay source became non-chronological")
        previous_ns = timestamp_ns
        if bool(record["simulated_blackout"]):
            blackout_samples += 1
        statuses[str(record["gnss_status"])] += 1
        ood_states[str(record["ml_ood_state"])] += 1
        callback(record)
    elapsed = max(perf_counter() - start, 1e-12)
    recording_duration = float(session.runtime["elapsed_seconds"].iloc[-1] - session.runtime["elapsed_seconds"].iloc[0])
    return ReplayResult(
        session_id=session.session_id,
        sample_count=len(session.runtime),
        recording_duration_s=recording_duration,
        normalized_rate_hz=session.achieved_rates_hz()["normalized"],
        replay_throughput_samples_per_s=len(session.runtime) / elapsed,
        blackout_samples=blackout_samples,
        gnss_status_counts=dict(sorted(statuses.items())),
        missing_sensors=session.missing_sensors,
        ml_ood_state_counts=dict(sorted(ood_states.items())),
    )
