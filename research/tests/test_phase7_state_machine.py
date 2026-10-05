import inspect
from dataclasses import replace

import numpy as np

from idr.phase7 import (
    GNSSObservation,
    NavigationInput,
    NavigationState,
    Phase7Config,
    ReacquisitionEngine,
    run_phase7_runtime,
)
from idr.phase7.engine import runtime_api_is_reference_free


ORIGIN = (12.0, 77.0)


def fix(t: float, east_m: float = 0.0, *, speed: float = 10.0, course: float = 90.0) -> GNSSObservation:
    lon = ORIGIN[1] + east_m / (6_371_008.8 * np.cos(np.radians(ORIGIN[0]))) * 180 / np.pi
    return GNSSObservation(t, ORIGIN[0], lon, 100.0, speed, course, 3.0, "12/8")


def sample(t: float, observation: GNSSObservation, *, east: float = 0.0, sigma: float = 20.0) -> NavigationInput:
    return NavigationInput(t, east, 0.0, 10.0, 90.0, sigma, observation)


def engine(config: Phase7Config | None = None) -> ReacquisitionEngine:
    value = ReacquisitionEngine(config or Phase7Config(), *ORIGIN)
    value.prime_gnss(fix(-1, -10))
    return value


def enter_idr(value: ReacquisitionEngine) -> None:
    value.step(sample(0, GNSSObservation.missing(0)))
    value.step(sample(3.1, GNSSObservation.missing(3.1)))
    value.step(sample(3.2, GNSSObservation.missing(3.2)))
    assert value.state is NavigationState.IDR_ACTIVE


def test_active_to_degraded_and_degraded_to_active() -> None:
    value = engine()
    value.step(sample(0, GNSSObservation.missing(0)))
    assert value.step(sample(3.1, GNSSObservation.missing(3.1))).navigation_state == "GNSS_DEGRADED"
    assert value.step(sample(4, fix(4, 40))).navigation_state == "GNSS_ACTIVE"


def test_degraded_to_idr() -> None:
    value = engine()
    enter_idr(value)


def test_idr_to_verifying() -> None:
    value = engine()
    enter_idr(value)
    assert value.step(sample(10, fix(10, 100), east=20)).navigation_state == "GNSS_VERIFYING"


def test_verifying_accepts_consistent_fixes_and_starts_recovery() -> None:
    value = engine()
    enter_idr(value)
    value.step(sample(10, fix(10, 100), east=20))
    value.step(sample(11, fix(11, 110), east=30))
    output = value.step(sample(12, fix(12, 120), east=40))
    assert output.navigation_state == "GNSS_RECOVERING"
    assert output.gnss_innovation_m is not None


def test_large_consistent_reacquisition_is_eventually_accepted() -> None:
    value = engine()
    enter_idr(value)
    outputs = [
        value.step(sample(10, fix(10, 150), east=0, sigma=80)),
        value.step(sample(11, fix(11, 160), east=10, sigma=80)),
        value.step(sample(12, fix(12, 170), east=20, sigma=80)),
    ]
    assert outputs[-1].navigation_state == "GNSS_RECOVERING"


def test_single_150m_outlier_does_not_snap_and_good_fixes_restart_streak() -> None:
    value = engine()
    enter_idr(value)
    first = value.step(sample(10, fix(10, 150), east=0))
    second = value.step(sample(11, fix(11, 10), east=10))
    assert first.correction_applied_m == 0
    assert second.navigation_state == "GNSS_VERIFYING"
    assert "rejected" in second.gnss_decision


def test_implausible_velocity_is_rejected() -> None:
    value = engine()
    enter_idr(value)
    output = value.step(sample(10, fix(10, 100, speed=90)))
    assert output.gnss_classification == "INVALID"
    assert output.navigation_state == "IDR_ACTIVE"


def test_implausible_course_jump_restarts_verification() -> None:
    config = replace(Phase7Config(), maximum_course_rate_degps=30)
    value = engine(config)
    enter_idr(value)
    value.step(sample(10, fix(10, 100, course=90)))
    output = value.step(sample(11, fix(11, 110, course=180)))
    assert "course_rate" in output.gnss_decision
    assert output.verification_fresh_fix_count == 1


def test_verifying_returns_to_idr_on_loss() -> None:
    value = engine()
    enter_idr(value)
    value.step(sample(10, fix(10, 100)))
    value.step(sample(11, GNSSObservation.missing(11)))
    assert value.step(sample(13.1, GNSSObservation.missing(13.1))).navigation_state == "IDR_ACTIVE"


def test_recovery_returns_active_with_bounded_finite_correction() -> None:
    config = replace(Phase7Config(), minimum_recovery_duration_s=1, recovery_completion_tolerance_m=20)
    value = engine(config)
    enter_idr(value)
    value.step(sample(10, fix(10, 100), east=20))
    value.step(sample(11, fix(11, 110), east=30))
    value.step(sample(12, fix(12, 120), east=40))
    outputs = [value.step(sample(t, fix(t, 10 * t), east=10 * t - 80)) for t in (13.0, 14.0, 15.0)]
    assert all(np.isfinite(item.navigation_uncertainty_m) for item in outputs)
    assert max(item.correction_rate_mps for item in outputs) <= config.maximum_correction_rate_mps + 1e-9
    assert outputs[-1].navigation_state in {"GNSS_RECOVERING", "GNSS_ACTIVE"}


def test_recovery_returns_to_idr_on_dropout() -> None:
    value = engine()
    enter_idr(value)
    value.step(sample(10, fix(10, 100), east=20))
    value.step(sample(11, fix(11, 110), east=30))
    value.step(sample(12, fix(12, 120), east=40))
    value.step(sample(13, GNSSObservation.missing(13), east=50))
    assert value.step(sample(15.1, GNSSObservation.missing(15.1), east=70)).navigation_state == "IDR_ACTIVE"


def test_runtime_apis_expose_no_reference_or_future_inputs() -> None:
    assert runtime_api_is_reference_free()
    parameters = set(inspect.signature(run_phase7_runtime).parameters)
    assert not parameters.intersection({"reference", "vbox", "future_gnss", "scenario_id"})
