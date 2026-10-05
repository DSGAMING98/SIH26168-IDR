"""Strict reader for the additive Phase 10 Android ``idr_output.csv`` stream."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


IDR_OUTPUT_COLUMNS = (
    "sequence_id", "elapsed_seconds", "monotonic_timestamp_ns", "wall_clock_utc",
    "local_east_m", "local_north_m", "estimated_latitude_deg", "estimated_longitude_deg",
    "estimated_speed_mps", "estimated_heading_deg", "horizontal_uncertainty_m", "confidence",
    "localization_state", "alignment_state", "motion_state", "ml_state", "ml_residual_mps",
    "ml_ood_exceedance", "dr_duration_seconds", "gnss_innovation_m", "last_correction_m",
    "engine_average_ms", "engine_p95_ms", "gnss_acquisition_state",
)
LOCALIZATION_STATES = frozenset(
    {"WAITING_FOR_GNSS", "CALIBRATING", "CALIBRATION_REQUIRED", "GNSS_ACTIVE", "GNSS_DEGRADED", "IDR_ACTIVE",
     "GNSS_VERIFYING", "GNSS_RECOVERING", "ERROR"}
)
ML_STATES = frozenset({"ML_WARMING", "ML_ACCEPTED", "ML_OOD_LIMITED", "ML_REJECTED", "ML_UNAVAILABLE"})


class AndroidIdrOutputError(ValueError):
    pass


def load_android_idr_output(session_directory: str | Path) -> pd.DataFrame:
    path = Path(session_directory) / "idr_output.csv"
    if not path.is_file():
        raise AndroidIdrOutputError("Missing Phase 10 recording file: idr_output.csv")
    frame = pd.read_csv(path)
    if tuple(frame.columns) != IDR_OUTPUT_COLUMNS:
        raise AndroidIdrOutputError("idr_output.csv schema mismatch")
    if frame.empty:
        raise AndroidIdrOutputError("idr_output.csv contains no estimator samples")
    for column in ("sequence_id", "elapsed_seconds", "monotonic_timestamp_ns"):
        values = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float)
        if not np.all(np.isfinite(values)) or np.any(np.diff(values) <= 0):
            raise AndroidIdrOutputError(f"{column} must be finite and strictly increasing")
    if not set(frame["localization_state"]).issubset(LOCALIZATION_STATES):
        raise AndroidIdrOutputError("Unknown Phase 10 localization state")
    if not set(frame["ml_state"]).issubset(ML_STATES):
        raise AndroidIdrOutputError("Unknown Phase 10 ML state")
    finite_required = (
        "local_east_m", "local_north_m", "estimated_speed_mps", "estimated_heading_deg",
        "dr_duration_seconds", "last_correction_m", "engine_average_ms", "engine_p95_ms",
    )
    values = frame.loc[:, finite_required].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    if not np.all(np.isfinite(values)):
        raise AndroidIdrOutputError("Estimator output contains non-finite required values")
    if bool((frame["estimated_speed_mps"] < 0).any()) or bool((frame["horizontal_uncertainty_m"].dropna() < 0).any()):
        raise AndroidIdrOutputError("Speed and uncertainty must be nonnegative")
    return frame
