from dataclasses import replace

import pytest

from idr.phase7 import GNSSClassification, GNSSFreshnessTracker, GNSSObservation, Phase7Config
from idr.phase7.gnss import circular_difference_deg


def fix(t: float, *, lat: float = 12.0, lon: float = 77.0, speed: float = 10.0, course: float = 90.0, accuracy: float = 3.0) -> GNSSObservation:
    return GNSSObservation(t, lat, lon, 100.0, speed, course, accuracy, "12/8")


def test_fresh_gnss_detection() -> None:
    tracker = GNSSFreshnessTracker(Phase7Config())
    assert tracker.classify(fix(0)).classification is GNSSClassification.FRESH
    assert tracker.classify(fix(1, lon=77.0001)).classification is GNSSClassification.FRESH


def test_repeated_stored_value_is_not_fresh() -> None:
    tracker = GNSSFreshnessTracker(Phase7Config())
    tracker.classify(fix(0))
    result = tracker.classify(fix(5))
    assert result.classification is GNSSClassification.REPEATED
    assert result.time_since_last_fresh_s == 5


def test_tiny_numerical_changes_are_tolerated() -> None:
    tracker = GNSSFreshnessTracker(Phase7Config())
    tracker.classify(fix(0))
    result = tracker.classify(fix(1, lat=12.00000001, lon=77.00000001, speed=10.01, course=90.1))
    assert result.classification is GNSSClassification.REPEATED


@pytest.mark.parametrize(
    ("observation", "reason"),
    [
        (GNSSObservation.missing(1), "no_gnss_fields"),
        (fix(1, speed=90), "reported_speed_implausible"),
        (fix(1, course=361), "course_out_of_range"),
        (fix(1, accuracy=100), "accuracy_invalid_or_excessive"),
    ],
)
def test_no_gnss_and_invalid_gnss(observation: GNSSObservation, reason: str) -> None:
    result = GNSSFreshnessTracker(Phase7Config()).classify(observation)
    assert result.reason == reason
    assert result.classification in {GNSSClassification.NO_GNSS, GNSSClassification.INVALID}


def test_heading_wrap_around() -> None:
    assert circular_difference_deg(1, 359) == pytest.approx(2)
    assert circular_difference_deg(359, 1) == pytest.approx(-2)


def test_tracker_is_deterministic() -> None:
    observations = [fix(0), fix(1), fix(2, lon=77.0001), GNSSObservation.missing(3)]
    outcomes = []
    for _ in range(2):
        tracker = GNSSFreshnessTracker(Phase7Config())
        outcomes.append([(r.classification.value, r.reason) for r in map(tracker.classify, observations)])
    assert outcomes[0] == outcomes[1]


def test_configuration_rejects_unsafe_values() -> None:
    with pytest.raises(ValueError):
        replace(Phase7Config(), required_consistent_fresh_fixes=1).validate()
    with pytest.raises(ValueError):
        replace(Phase7Config(), maximum_correction_rate_mps=0).validate()
