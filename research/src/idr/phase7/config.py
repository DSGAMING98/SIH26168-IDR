"""Frozen configuration structure for Phase 7."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class Phase7Config:
    position_change_tolerance_m: float = 0.5
    speed_change_tolerance_mps: float = 0.25
    course_change_tolerance_deg: float = 2.0
    altitude_change_tolerance_m: float = 0.5
    maximum_gnss_accuracy_m: float = 50.0
    maximum_reported_speed_mps: float = 55.0
    degraded_grace_s: float = 3.0
    stale_to_idr_timeout_s: float = 18.0
    no_gnss_to_idr_timeout_s: float = 2.0
    verifying_loss_timeout_s: float = 2.0
    required_consistent_fresh_fixes: int = 3
    maximum_verification_gap_s: float = 20.0
    maximum_candidate_motion_speed_mps: float = 55.0
    minimum_course_motion_m: float = 3.0
    maximum_course_residual_deg: float = 80.0
    maximum_course_rate_degps: float = 120.0
    innovation_floor_m: float = 30.0
    innovation_sigma_multiplier: float = 4.0
    recovery_time_constant_s: float = 4.0
    recovery_trust_ramp_s: float = 4.0
    maximum_correction_rate_mps: float = 8.0
    minimum_recovery_duration_s: float = 6.0
    recovery_completion_tolerance_m: float = 5.0
    minimum_gnss_gain: float = 0.15
    maximum_gnss_gain: float = 0.85
    post_blackout_tail_s: float = 120.0

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "Phase7Config":
        allowed = {field.name for field in cls.__dataclass_fields__.values()}
        unknown = set(values).difference(allowed)
        if unknown:
            raise ValueError(f"Unknown Phase 7 settings: {sorted(unknown)}")
        result = cls(**values)
        result.validate()
        return result

    def validate(self) -> None:
        values = asdict(self)
        count = int(values.pop("required_consistent_fresh_fixes"))
        numeric = np.asarray(list(values.values()), dtype=float)
        if not np.all(np.isfinite(numeric)) or np.any(numeric < 0):
            raise ValueError("Phase 7 settings must be finite and non-negative.")
        if count < 2:
            raise ValueError("At least two genuinely fresh fixes are required.")
        if self.maximum_gnss_gain > 1 or self.minimum_gnss_gain > self.maximum_gnss_gain:
            raise ValueError("GNSS gain bounds must satisfy 0 <= min <= max <= 1.")
        if self.stale_to_idr_timeout_s <= self.degraded_grace_s:
            raise ValueError("Stale timeout must exceed the degraded grace interval.")
        if self.maximum_correction_rate_mps <= 0 or self.recovery_time_constant_s <= 0:
            raise ValueError("Recovery rate and time constant must be positive.")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
