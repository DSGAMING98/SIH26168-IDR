from dataclasses import replace

import numpy as np

from idr.phase7 import GNSSObservation, NavigationInput, Phase7Config, ReacquisitionEngine


def fix(t: float, east: float) -> GNSSObservation:
    lon = 77.0 + east / (6_371_008.8 * np.cos(np.radians(12.0))) * 180 / np.pi
    return GNSSObservation(t, 12.0, lon, 100.0, 10.0, 90.0, 3.0)


def inp(t: float, east: float, observation: GNSSObservation) -> NavigationInput:
    return NavigationInput(t, east, 0, 10, 90, 40, observation)


def recovery_outputs() -> list:
    config = replace(Phase7Config(), minimum_recovery_duration_s=2)
    engine = ReacquisitionEngine(config, 12, 77)
    engine.prime_gnss(fix(-1, -10))
    for t in (0, 3.1, 3.2):
        engine.step(inp(t, t * 10, GNSSObservation.missing(t)))
    outputs = [engine.step(inp(10, 20, fix(10, 100)))]
    outputs.append(engine.step(inp(11, 30, fix(11, 110))))
    outputs.append(engine.step(inp(12, 40, fix(12, 120))))
    outputs.extend(engine.step(inp(t, 10 * t - 80, fix(t, 10 * t))) for t in np.arange(12.1, 18.1, 0.1))
    return outputs


def test_smooth_transition_is_smaller_than_hard_snap() -> None:
    outputs = recovery_outputs()
    hard_snap = 80.0
    smooth = max(item.correction_applied_m for item in outputs)
    assert smooth < hard_snap / 5


def test_correction_rate_is_bounded() -> None:
    outputs = recovery_outputs()
    assert max(item.correction_rate_mps for item in outputs) <= Phase7Config().maximum_correction_rate_mps + 1e-9


def test_reacquisition_is_deterministic() -> None:
    first = [(item.navigation_state, item.navigation_east_m, item.gnss_decision) for item in recovery_outputs()]
    second = [(item.navigation_state, item.navigation_east_m, item.gnss_decision) for item in recovery_outputs()]
    assert first == second


def test_disabled_phase7_is_exact_idr_passthrough() -> None:
    engine = ReacquisitionEngine(Phase7Config(), 12, 77, enabled=False)
    output = engine.step(inp(0, 123.45, fix(0, 500)))
    assert output.navigation_east_m == 123.45
    assert output.navigation_north_m == 0
    assert output.gnss_decision == "PASSTHROUGH"
