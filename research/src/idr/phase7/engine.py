"""Deterministic navigation-state machine and bounded GNSS recovery fusion."""

from __future__ import annotations

import inspect
import math
import time
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

import numpy as np

from ..evaluation import geodetic_to_local_xy_m, local_xy_to_geodetic
from .config import Phase7Config
from .gnss import (
    GNSSClassification,
    GNSSFreshnessResult,
    GNSSFreshnessTracker,
    GNSSObservation,
    circular_difference_deg,
    initial_bearing_deg,
)


class NavigationState(str, Enum):
    GNSS_ACTIVE = "GNSS_ACTIVE"
    GNSS_DEGRADED = "GNSS_DEGRADED"
    IDR_ACTIVE = "IDR_ACTIVE"
    GNSS_VERIFYING = "GNSS_VERIFYING"
    GNSS_RECOVERING = "GNSS_RECOVERING"


@dataclass(frozen=True)
class NavigationInput:
    elapsed_s: float
    idr_east_m: float
    idr_north_m: float
    idr_speed_mps: float
    idr_yaw_deg: float
    idr_position_sigma_m: float
    gnss: GNSSObservation


@dataclass(frozen=True)
class NavigationOutput:
    elapsed_s: float
    navigation_east_m: float
    navigation_north_m: float
    navigation_latitude_deg: float
    navigation_longitude_deg: float
    navigation_state: str
    judge_status: str
    gnss_classification: str
    gnss_reason: str
    gnss_decision: str
    seconds_since_last_fresh_fix: float
    dead_reckoning_duration_s: float
    verification_fresh_fix_count: int
    recovery_progress: float
    navigation_uncertainty_m: float
    gnss_innovation_m: float | None
    innovation_gate_m: float | None
    innovation_within_gate: bool | None
    correction_applied_m: float
    correction_rate_mps: float
    offset_east_m: float
    offset_north_m: float
    state_changed: bool
    previous_state: str
    online_latency_ms: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


JUDGE_STATUS = {
    NavigationState.GNSS_ACTIVE: "GNSS ACTIVE",
    NavigationState.GNSS_DEGRADED: "GNSS DEGRADED",
    NavigationState.IDR_ACTIVE: "GNSS LOST - INTELLIGENT DEAD RECKONING ACTIVE",
    NavigationState.GNSS_VERIFYING: "GNSS SIGNAL DETECTED - VERIFYING FIX",
    NavigationState.GNSS_RECOVERING: "GNSS VERIFIED - SMOOTH RECOVERY ACTIVE",
}


class ReacquisitionEngine:
    """One-sample-at-a-time causal engine; it has no reference or future API."""

    def __init__(
        self,
        config: Phase7Config,
        origin_latitude_deg: float,
        origin_longitude_deg: float,
        *,
        enabled: bool = True,
    ):
        config.validate()
        self.config = config
        self.origin_latitude_deg = float(origin_latitude_deg)
        self.origin_longitude_deg = float(origin_longitude_deg)
        self.enabled = bool(enabled)
        self.freshness = GNSSFreshnessTracker(config)
        self.state = NavigationState.GNSS_ACTIVE
        self.last_elapsed_s: float | None = None
        self.interruption_start_s: float | None = None
        self.no_gnss_start_s: float | None = None
        self.idr_start_s: float | None = None
        self.verification_candidates: list[GNSSObservation] = []
        self.last_consistent_fix: GNSSObservation | None = None
        self.recovery_start_s: float | None = None
        self.offset = np.zeros(2, dtype=float)
        self.target_offset: np.ndarray | None = None
        self.recovery_initial_residual_m = 0.0
        self.last_gnss_accuracy_m: float | None = None
        self.transition_history: list[dict[str, Any]] = []

    def prime_gnss(self, observation: GNSSObservation) -> GNSSFreshnessResult:
        """Supply strictly pre-runtime observations in timestamp order."""

        result = self.freshness.classify(observation)
        if result.classification is GNSSClassification.FRESH:
            self.last_consistent_fix = observation
            self.last_gnss_accuracy_m = observation.accuracy_m
        return result

    def _transition(self, state: NavigationState, elapsed_s: float, reason: str) -> bool:
        if state is self.state:
            return False
        previous = self.state
        self.state = state
        self.transition_history.append(
            {"elapsed_s": float(elapsed_s), "from": previous.value, "to": state.value, "reason": reason}
        )
        if state is NavigationState.IDR_ACTIVE and self.idr_start_s is None:
            self.idr_start_s = float(elapsed_s)
        if state is NavigationState.GNSS_RECOVERING:
            self.recovery_start_s = float(elapsed_s)
        return True

    def _local_gnss(self, observation: GNSSObservation) -> np.ndarray:
        assert observation.latitude_deg is not None and observation.longitude_deg is not None
        local = geodetic_to_local_xy_m(
            [observation.latitude_deg], [observation.longitude_deg],
            self.origin_latitude_deg, self.origin_longitude_deg,
        )
        return np.array([local.x_east_m[0], local.y_north_m[0]], dtype=float)

    def _candidate_consistent(self, previous: GNSSObservation, current: GNSSObservation) -> tuple[bool, str]:
        dt = current.elapsed_s - previous.elapsed_s
        if dt <= 0 or dt > self.config.maximum_verification_gap_s:
            return False, "candidate_time_gap_invalid"
        previous_xy = self._local_gnss(previous)
        current_xy = self._local_gnss(current)
        displacement = float(np.linalg.norm(current_xy - previous_xy))
        if displacement / dt > self.config.maximum_candidate_motion_speed_mps:
            return False, "candidate_displacement_speed_implausible"
        assert current.speed_mps is not None and current.course_deg is not None and previous.course_deg is not None
        if current.speed_mps > self.config.maximum_reported_speed_mps:
            return False, "candidate_reported_speed_implausible"
        course_rate = abs(circular_difference_deg(current.course_deg, previous.course_deg)) / dt
        if course_rate > self.config.maximum_course_rate_degps:
            return False, "candidate_course_rate_implausible"
        if displacement >= self.config.minimum_course_motion_m:
            motion_bearing = initial_bearing_deg(previous, current)
            if abs(circular_difference_deg(current.course_deg, motion_bearing)) > self.config.maximum_course_residual_deg:
                return False, "candidate_course_motion_inconsistent"
        return True, "candidate_consistent"

    def _innovation(self, navigation_xy: np.ndarray, observation: GNSSObservation, sigma_m: float) -> tuple[float, float, bool]:
        innovation = float(np.linalg.norm(self._local_gnss(observation) - navigation_xy))
        accuracy = max(1.0, float(observation.accuracy_m or 1.0))
        gate = max(
            self.config.innovation_floor_m,
            self.config.innovation_sigma_multiplier * math.hypot(max(0.0, sigma_m), accuracy),
        )
        return innovation, gate, innovation <= gate

    def _refresh_target(self, navigation_xy: np.ndarray, observation: GNSSObservation, sigma_m: float) -> tuple[float, float, bool]:
        gnss_xy = self._local_gnss(observation)
        innovation, gate, within = self._innovation(navigation_xy, observation, sigma_m)
        accuracy = max(1.0, float(observation.accuracy_m or 1.0))
        variance_ratio = sigma_m * sigma_m / max(sigma_m * sigma_m + accuracy * accuracy, 1e-9)
        gain = float(np.clip(variance_ratio, self.config.minimum_gnss_gain, self.config.maximum_gnss_gain))
        self.target_offset = self.offset + gain * (gnss_xy - navigation_xy)
        self.recovery_initial_residual_m = max(
            self.recovery_initial_residual_m,
            float(np.linalg.norm(self.target_offset - self.offset)),
        )
        self.last_gnss_accuracy_m = observation.accuracy_m
        return innovation, gate, within

    def _advance_offset(self, dt_s: float, elapsed_s: float) -> tuple[float, float, float]:
        if self.target_offset is None or dt_s <= 0:
            return 0.0, 0.0, self._recovery_progress()
        if self.state not in {NavigationState.GNSS_RECOVERING, NavigationState.GNSS_ACTIVE, NavigationState.GNSS_DEGRADED}:
            return 0.0, 0.0, self._recovery_progress()
        if self.state is NavigationState.GNSS_RECOVERING and self.recovery_start_s is not None:
            trust = float(np.clip((elapsed_s - self.recovery_start_s) / max(self.config.recovery_trust_ramp_s, 1e-9), 0.05, 1.0))
        else:
            trust = 1.0
        alpha = trust * (1.0 - math.exp(-dt_s / self.config.recovery_time_constant_s))
        desired = alpha * (self.target_offset - self.offset)
        maximum = self.config.maximum_correction_rate_mps * dt_s
        magnitude = float(np.linalg.norm(desired))
        if magnitude > maximum > 0:
            desired *= maximum / magnitude
            magnitude = maximum
        self.offset += desired
        return magnitude, magnitude / dt_s, self._recovery_progress()

    def _recovery_progress(self) -> float:
        if self.target_offset is None or self.recovery_initial_residual_m <= 0:
            return 0.0
        remaining = float(np.linalg.norm(self.target_offset - self.offset))
        return float(np.clip(1.0 - remaining / self.recovery_initial_residual_m, 0.0, 1.0))

    def step(self, sample: NavigationInput) -> NavigationOutput:
        started = time.perf_counter()
        values = np.array(
            [sample.elapsed_s, sample.idr_east_m, sample.idr_north_m, sample.idr_speed_mps, sample.idr_yaw_deg, sample.idr_position_sigma_m],
            dtype=float,
        )
        if not np.all(np.isfinite(values)):
            raise ValueError("Navigation input must be finite.")
        if self.last_elapsed_s is not None and sample.elapsed_s <= self.last_elapsed_s:
            raise ValueError("Navigation timestamps must be strictly increasing.")
        dt = 0.0 if self.last_elapsed_s is None else sample.elapsed_s - self.last_elapsed_s
        previous_state = self.state
        if not self.enabled:
            latitude, longitude = local_xy_to_geodetic(
                [sample.idr_east_m], [sample.idr_north_m], self.origin_latitude_deg, self.origin_longitude_deg
            )
            self.last_elapsed_s = sample.elapsed_s
            return NavigationOutput(
                sample.elapsed_s, sample.idr_east_m, sample.idr_north_m,
                float(latitude[0]), float(longitude[0]), self.state.value, JUDGE_STATUS[self.state],
                "DISABLED", "phase7_disabled", "PASSTHROUGH", math.inf, 0.0, 0, 0.0,
                sample.idr_position_sigma_m, None, None, None, 0.0, 0.0, 0.0, 0.0,
                False, previous_state.value, (time.perf_counter() - started) * 1000.0,
            )
        freshness = self.freshness.classify(sample.gnss)
        kind = freshness.classification
        if kind is GNSSClassification.FRESH:
            self.interruption_start_s = None
            self.no_gnss_start_s = None
        else:
            if self.interruption_start_s is None:
                self.interruption_start_s = sample.elapsed_s
            if kind in {GNSSClassification.NO_GNSS, GNSSClassification.INVALID}:
                if self.no_gnss_start_s is None:
                    self.no_gnss_start_s = sample.elapsed_s
            else:
                self.no_gnss_start_s = None
        interruption_age = 0.0 if self.interruption_start_s is None else sample.elapsed_s - self.interruption_start_s
        no_gnss_age = 0.0 if self.no_gnss_start_s is None else sample.elapsed_s - self.no_gnss_start_s
        navigation_before = np.array([sample.idr_east_m, sample.idr_north_m], dtype=float) + self.offset
        decision = freshness.reason
        innovation = gate = None
        within_gate = None
        state_changed = False

        if self.state is NavigationState.GNSS_ACTIVE:
            if kind is GNSSClassification.FRESH:
                if self.last_consistent_fix is None or self._candidate_consistent(self.last_consistent_fix, sample.gnss)[0]:
                    self.last_consistent_fix = sample.gnss
                    innovation, gate, within_gate = self._refresh_target(navigation_before, sample.gnss, sample.idr_position_sigma_m)
                    decision = "fresh_gnss_accepted_active"
                else:
                    decision = "fresh_gnss_rejected_inconsistent_active"
            elif interruption_age >= self.config.degraded_grace_s:
                state_changed |= self._transition(NavigationState.GNSS_DEGRADED, sample.elapsed_s, "freshness_grace_exceeded")
        elif self.state is NavigationState.GNSS_DEGRADED:
            if kind is GNSSClassification.FRESH:
                self.last_consistent_fix = sample.gnss
                innovation, gate, within_gate = self._refresh_target(navigation_before, sample.gnss, sample.idr_position_sigma_m)
                state_changed |= self._transition(NavigationState.GNSS_ACTIVE, sample.elapsed_s, "fresh_fix_restored")
                decision = "fresh_gnss_restored"
            elif (
                no_gnss_age >= self.config.no_gnss_to_idr_timeout_s
                or freshness.time_since_last_fresh_s >= self.config.stale_to_idr_timeout_s
            ):
                state_changed |= self._transition(NavigationState.IDR_ACTIVE, sample.elapsed_s, "gnss_unavailable_or_stale")
                decision = "idr_activated"
        elif self.state is NavigationState.IDR_ACTIVE:
            if kind is GNSSClassification.FRESH:
                self.verification_candidates = [sample.gnss]
                self.last_consistent_fix = sample.gnss
                state_changed |= self._transition(NavigationState.GNSS_VERIFYING, sample.elapsed_s, "fresh_candidate_detected")
                innovation, gate, within_gate = self._innovation(navigation_before, sample.gnss, sample.idr_position_sigma_m)
                decision = "candidate_1_of_%d" % self.config.required_consistent_fresh_fixes
        elif self.state is NavigationState.GNSS_VERIFYING:
            if kind is GNSSClassification.FRESH:
                previous = self.verification_candidates[-1] if self.verification_candidates else sample.gnss
                consistent, reason = self._candidate_consistent(previous, sample.gnss)
                innovation, gate, within_gate = self._innovation(navigation_before, sample.gnss, sample.idr_position_sigma_m)
                if consistent:
                    self.verification_candidates.append(sample.gnss)
                    self.last_consistent_fix = sample.gnss
                    decision = f"candidate_{len(self.verification_candidates)}_of_{self.config.required_consistent_fresh_fixes}"
                    if len(self.verification_candidates) >= self.config.required_consistent_fresh_fixes:
                        self.recovery_initial_residual_m = 0.0
                        innovation, gate, within_gate = self._refresh_target(navigation_before, sample.gnss, sample.idr_position_sigma_m)
                        state_changed |= self._transition(NavigationState.GNSS_RECOVERING, sample.elapsed_s, "consistent_fix_streak_verified")
                        decision = "gnss_verified_recovery_started"
                else:
                    self.verification_candidates = [sample.gnss]
                    self.last_consistent_fix = sample.gnss
                    decision = f"candidate_rejected_{reason};restart_1_of_{self.config.required_consistent_fresh_fixes}"
            elif kind is GNSSClassification.INVALID:
                decision = f"candidate_rejected_{freshness.reason}"
            if (
                kind is GNSSClassification.NO_GNSS
                and no_gnss_age >= self.config.verifying_loss_timeout_s
            ) or (
                self.verification_candidates
                and sample.elapsed_s - self.verification_candidates[-1].elapsed_s > self.config.maximum_verification_gap_s
            ):
                self.verification_candidates = []
                state_changed |= self._transition(NavigationState.IDR_ACTIVE, sample.elapsed_s, "verification_signal_lost")
                decision = "verification_aborted_to_idr"
        elif self.state is NavigationState.GNSS_RECOVERING:
            if kind is GNSSClassification.FRESH:
                previous = self.last_consistent_fix
                consistent, reason = (True, "first_recovery_fix") if previous is None else self._candidate_consistent(previous, sample.gnss)
                if consistent:
                    self.last_consistent_fix = sample.gnss
                    innovation, gate, within_gate = self._refresh_target(navigation_before, sample.gnss, sample.idr_position_sigma_m)
                    decision = "fresh_gnss_accepted_recovery"
                else:
                    decision = f"fresh_gnss_rejected_{reason}"
            if (
                (kind is GNSSClassification.NO_GNSS and no_gnss_age >= self.config.no_gnss_to_idr_timeout_s)
                or freshness.time_since_last_fresh_s >= self.config.stale_to_idr_timeout_s
            ):
                state_changed |= self._transition(NavigationState.IDR_ACTIVE, sample.elapsed_s, "gnss_lost_during_recovery")
                decision = "recovery_aborted_to_idr"

        correction_m, correction_rate, progress = self._advance_offset(dt, sample.elapsed_s)
        if self.state is NavigationState.GNSS_RECOVERING and self.recovery_start_s is not None and self.target_offset is not None:
            if (
                sample.elapsed_s - self.recovery_start_s >= self.config.minimum_recovery_duration_s
                and float(np.linalg.norm(self.target_offset - self.offset)) <= self.config.recovery_completion_tolerance_m
            ):
                state_changed |= self._transition(NavigationState.GNSS_ACTIVE, sample.elapsed_s, "bounded_recovery_converged")
                decision = "recovery_complete_gnss_active"
                self.verification_candidates = []
        navigation_xy = np.array([sample.idr_east_m, sample.idr_north_m], dtype=float) + self.offset
        latitude, longitude = local_xy_to_geodetic(
            [navigation_xy[0]], [navigation_xy[1]], self.origin_latitude_deg, self.origin_longitude_deg
        )
        dead_reckoning_duration = 0.0 if self.idr_start_s is None else max(0.0, sample.elapsed_s - self.idr_start_s)
        accuracy = sample.gnss.accuracy_m if sample.gnss.accuracy_m is not None else self.last_gnss_accuracy_m
        navigation_uncertainty = (1.0 - progress) * sample.idr_position_sigma_m + progress * max(1.0, float(accuracy or sample.idr_position_sigma_m))
        self.last_elapsed_s = sample.elapsed_s
        return NavigationOutput(
            elapsed_s=sample.elapsed_s,
            navigation_east_m=float(navigation_xy[0]),
            navigation_north_m=float(navigation_xy[1]),
            navigation_latitude_deg=float(latitude[0]),
            navigation_longitude_deg=float(longitude[0]),
            navigation_state=self.state.value,
            judge_status=JUDGE_STATUS[self.state],
            gnss_classification=kind.value,
            gnss_reason=freshness.reason,
            gnss_decision=decision,
            seconds_since_last_fresh_fix=float(freshness.time_since_last_fresh_s),
            dead_reckoning_duration_s=dead_reckoning_duration,
            verification_fresh_fix_count=len(self.verification_candidates),
            recovery_progress=progress,
            navigation_uncertainty_m=float(navigation_uncertainty),
            gnss_innovation_m=innovation,
            innovation_gate_m=gate,
            innovation_within_gate=within_gate,
            correction_applied_m=correction_m,
            correction_rate_mps=correction_rate,
            offset_east_m=float(self.offset[0]),
            offset_north_m=float(self.offset[1]),
            state_changed=state_changed,
            previous_state=previous_state.value,
            online_latency_ms=(time.perf_counter() - started) * 1000.0,
        )


def runtime_api_is_reference_free() -> bool:
    parameters = inspect.signature(ReacquisitionEngine.step).parameters
    forbidden = {"reference", "vbox", "future_gnss", "route", "destination", "scenario"}
    return forbidden.isdisjoint(parameters)
