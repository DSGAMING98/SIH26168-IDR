from __future__ import annotations

import math
import time

import pytest

from idr.edge import (
    EdgeIdrConfig,
    EdgeIdrEngine,
    ExternalGnssFix,
    ExternalImuSample,
    RoadSegment,
    StreamingRoadMatcher,
)


def sample(index: int, *, hz: float = 200.0, acceleration: float = 0.0, yaw_rate: float = 0.0, stationary: bool = False) -> ExternalImuSample:
    return ExternalImuSample(
        timestamp_s=index / hz,
        acceleration_mps2=(acceleration, 0.0, 0.0),
        angular_rate_radps=(0.0, 0.0, yaw_rate),
        stationary_hint=stationary,
    )


def test_accepts_and_propagates_native_200_hz_external_imu() -> None:
    engine = EdgeIdrEngine()
    for index in range(401):
        state = engine.ingest_imu(sample(index, acceleration=1.0))

    assert state.samples_processed == 401
    assert state.update_rate_hz == pytest.approx(200.0, rel=1e-3)
    assert state.speed_mps == pytest.approx(2.0, abs=0.03)
    assert state.north_m == pytest.approx(2.0, abs=0.05)
    assert state.east_m == pytest.approx(0.0, abs=1e-9)


def test_non_holonomic_model_does_not_integrate_lateral_acceleration() -> None:
    engine = EdgeIdrEngine()
    for index in range(401):
        state = engine.ingest_imu(
            ExternalImuSample(index / 200.0, (0.0, 5.0, 0.0), (0.0, 0.0, 0.0))
        )

    assert state.speed_mps == pytest.approx(0.0, abs=1e-9)
    assert state.east_m == pytest.approx(0.0, abs=1e-9)
    assert state.north_m == pytest.approx(0.0, abs=1e-9)


def test_stationary_hint_learns_bias_and_prevents_speed_runaway() -> None:
    engine = EdgeIdrEngine()
    for index in range(601):
        state = engine.ingest_imu(sample(index, acceleration=0.12, stationary=True))

    assert state.stationary
    assert state.speed_mps == pytest.approx(0.0, abs=1e-9)
    assert state.acceleration_bias_mps2 > 0.10
    assert state.north_m < 0.08


def test_ml_speed_updates_are_bounded_and_run_at_ten_hz() -> None:
    calls = 0

    def correction(_window):
        nonlocal calls
        calls += 1
        return 100.0

    engine = EdgeIdrEngine(ml_speed_correction=correction)
    for index in range(801):
        state = engine.ingest_imu(sample(index))

    assert 19 <= calls <= 22
    assert state.ml_updates == calls
    assert state.speed_mps <= state.ml_updates * 3.0


def test_offline_road_constraint_is_bounded_and_heading_aware() -> None:
    matcher = StreamingRoadMatcher(
        [RoadSegment(-100.0, 0.0, 100.0, 0.0)],
        search_radius_m=20.0,
        maximum_correction_m=2.0,
        gain=0.5,
    )
    matched = matcher.constrain(10.0, 10.0, math.pi / 2.0)

    assert matched is not None
    assert matched[0] == pytest.approx(10.0)
    assert matched[1] == pytest.approx(8.0)


def test_gnss_measurement_reanchors_position_speed_and_course() -> None:
    engine = EdgeIdrEngine()
    engine.ingest_imu(sample(0))
    state = engine.ingest_gnss(ExternalGnssFix(0.0, 10.0, 20.0, 8.0, math.pi / 2.0, 2.0))

    assert state.east_m > 3.0
    assert state.north_m > 6.0
    assert state.speed_mps > 3.0
    assert state.yaw_rad > 0.3


def test_processing_capacity_exceeds_200_hz_by_large_margin() -> None:
    engine = EdgeIdrEngine()
    samples = [sample(index) for index in range(20_000)]
    started = time.perf_counter()
    for item in samples:
        engine.ingest_imu(item)
    elapsed = time.perf_counter() - started

    assert len(samples) / elapsed > 2_000.0


def test_rejects_out_of_order_or_gapped_samples() -> None:
    engine = EdgeIdrEngine()
    engine.ingest_imu(sample(0))
    with pytest.raises(ValueError, match="strictly increasing"):
        engine.ingest_imu(sample(0))
    with pytest.raises(ValueError, match="gap"):
        engine.ingest_imu(ExternalImuSample(1.0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)))
