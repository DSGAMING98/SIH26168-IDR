"""Offline-only validation of Phase 11 Android field-test sessions.

The Android phone's physical GPS stream is an evaluation proxy, not
survey-grade ground truth. It is quality-gated and interpolated only after the
runtime estimator output has been loaded. Nothing in this module is part of the
on-device runtime path.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from idr.evaluation import (
    great_circle_distance_m,
    path_distance_m,
    position_error_series_m,
    summarize_position_errors,
)
from idr.phase10.android_idr import AndroidIdrOutputError, load_android_idr_output
from idr.phase9.android_session import load_android_session


MAX_REFERENCE_ACCURACY_M = 50.0
MAX_REFERENCE_SPEED_MPS = 80.0


@dataclass(frozen=True)
class ReferenceQuality:
    source: str
    total_points: int
    retained_points: int
    rejected_points: int
    rejection_reasons: dict[str, int]
    accuracy_threshold_m: float = MAX_REFERENCE_ACCURACY_M
    speed_threshold_mps: float = MAX_REFERENCE_SPEED_MPS


@dataclass(frozen=True)
class SessionValidationResult:
    session_id: str
    evaluable: bool
    reference_wording: str
    quality: ReferenceQuality
    session_summary: dict[str, object]
    blackout_metrics: tuple[dict[str, object], ...]
    output_directory: Path | None
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "evaluable": self.evaluable,
            "reference_wording": self.reference_wording,
            "reference_quality": asdict(self.quality),
            "session_summary": self.session_summary,
            "blackouts": list(self.blackout_metrics),
            "limitations": list(self.limitations),
        }


def _groups(mask: np.ndarray) -> list[tuple[int, int]]:
    indices = np.flatnonzero(mask)
    if indices.size == 0:
        return []
    split = np.flatnonzero(np.diff(indices) > 1) + 1
    return [(int(part[0]), int(part[-1])) for part in np.split(indices, split)]


def _reference_from_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    aliases = {
        "time_s": "elapsed_seconds",
        "latitude": "latitude_deg",
        "lat": "latitude_deg",
        "longitude": "longitude_deg",
        "lon": "longitude_deg",
        "accuracy": "accuracy_m",
        "speed": "speed_mps",
    }
    frame = frame.rename(columns={name: aliases.get(name.lower(), name.lower()) for name in frame.columns})
    required = {"elapsed_seconds", "latitude_deg", "longitude_deg"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Reference CSV missing columns: {sorted(missing)}")
    return frame


def _reference_from_gpx(path: Path) -> pd.DataFrame:
    root = ET.parse(path).getroot()
    points: list[dict[str, object]] = []
    for point in root.findall(".//{*}trkpt"):
        time = point.find("{*}time")
        points.append({
            "latitude_deg": point.attrib.get("lat"),
            "longitude_deg": point.attrib.get("lon"),
            "time": None if time is None else time.text,
        })
    frame = pd.DataFrame(points)
    if frame.empty:
        raise ValueError("Reference GPX contains no track points")
    wall = pd.to_datetime(frame.pop("time"), utc=True, errors="coerce")
    if wall.isna().any():
        raise ValueError("Reference GPX track points require valid UTC timestamps")
    frame["elapsed_seconds"] = (wall - wall.iloc[0]).dt.total_seconds()
    return frame


def _quality_gate_reference(frame: pd.DataFrame, source: str) -> tuple[pd.DataFrame, ReferenceQuality, pd.DataFrame]:
    work = frame.copy()
    total = len(work)
    for name in ("elapsed_seconds", "latitude_deg", "longitude_deg", "accuracy_m", "speed_mps"):
        if name in work:
            work[name] = pd.to_numeric(work[name], errors="coerce")
    reasons: list[str] = []
    previous_time: float | None = None
    for row in work.to_dict("records"):
        reason = ""
        time_s = row.get("elapsed_seconds")
        lat = row.get("latitude_deg")
        lon = row.get("longitude_deg")
        if not all(np.isfinite(value) for value in (time_s, lat, lon)):
            reason = "non_finite_core"
        elif not (-90.0 <= float(lat) <= 90.0 and -180.0 <= float(lon) <= 180.0):
            reason = "invalid_coordinate"
        elif previous_time is not None and float(time_s) <= previous_time:
            reason = "non_monotonic_timestamp"
        elif str(row.get("callback_status", "")).upper() == "INVALID":
            reason = "invalid_callback"
        elif pd.notna(row.get("accuracy_m")) and float(row["accuracy_m"]) > MAX_REFERENCE_ACCURACY_M:
            reason = "poor_horizontal_accuracy"
        elif pd.notna(row.get("speed_mps")) and not (0.0 <= float(row["speed_mps"]) <= MAX_REFERENCE_SPEED_MPS):
            reason = "implausible_speed"
        if reason == "":
            previous_time = float(time_s)
        reasons.append(reason)
    audit = work.assign(rejection_reason=reasons, retained=np.array(reasons) == "")
    retained = audit.loc[audit["retained"], ["elapsed_seconds", "latitude_deg", "longitude_deg"]].copy()
    counts = audit.loc[~audit["retained"], "rejection_reason"].value_counts().sort_index().to_dict()
    quality = ReferenceQuality(source, total, len(retained), total - len(retained), {str(k): int(v) for k, v in counts.items()})
    return retained.reset_index(drop=True), quality, audit


def load_evaluation_reference(
    session_directory: str | Path,
    reference_path: str | Path | None = None,
) -> tuple[pd.DataFrame, ReferenceQuality, pd.DataFrame]:
    """Load and quality-gate the evaluator-only reference track."""

    session_root = Path(session_directory).resolve()
    if reference_path is None:
        source_path = session_root / "gnss_raw.csv"
        if not source_path.is_file():
            empty = pd.DataFrame(columns=["elapsed_seconds", "latitude_deg", "longitude_deg"])
            quality = ReferenceQuality("phone-GNSS evaluation reference", 0, 0, 0, {})
            return empty, quality, empty.assign(rejection_reason=pd.Series(dtype=str), retained=pd.Series(dtype=bool))
        raw = pd.read_csv(source_path)
        source = "phone-GNSS evaluation reference"
    else:
        source_path = Path(reference_path).resolve()
        source = f"independent evaluation reference ({source_path.suffix.lower().lstrip('.')})"
        raw = _reference_from_gpx(source_path) if source_path.suffix.lower() == ".gpx" else _reference_from_csv(source_path)
    return _quality_gate_reference(raw, source)


def _fractions(series: pd.Series) -> dict[str, float]:
    total = max(1, len(series))
    return {str(key): float(value / total) for key, value in series.value_counts().sort_index().items()}


def _safe_stat(values: pd.Series, fn: str) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=float)
    if numeric.size == 0:
        return None
    return float(np.median(numeric) if fn == "median" else np.max(numeric) if fn == "max" else np.mean(numeric))


def _session_summary(session: object, estimator: pd.DataFrame | None) -> dict[str, object]:
    metadata = session.metadata  # type: ignore[attr-defined]
    runtime = session.runtime  # type: ignore[attr-defined]
    phase11 = metadata.get("phase11_runtime_summary") or {}
    summary: dict[str, object] = {
        "device": " ".join(filter(None, [metadata.get("device_manufacturer"), metadata.get("device_model")])),
        "android_version": metadata.get("android_version"),
        "app_version": metadata.get("app_version"),
        "duration_seconds": float(runtime["elapsed_seconds"].iloc[-1] - runtime["elapsed_seconds"].iloc[0]),
        "runtime_samples": len(runtime),
        "raw_physical_gnss_samples": len(session.raw_physical_gnss),  # type: ignore[attr-defined]
        "observed_rates_hz": metadata.get("observed_rates"),
        "field_test": metadata.get("field_test"),
        "engine_average_ms": phase11.get("engine_average_ms"),
        "engine_p95_ms": phase11.get("engine_p95_ms"),
        "battery_start_percent": phase11.get("battery_start_percent"),
        "battery_end_percent": phase11.get("battery_end_percent"),
        "battery_temperature_start_c": phase11.get("battery_temperature_start_c"),
        "battery_temperature_end_c": phase11.get("battery_temperature_end_c"),
        "thermal_status_start": phase11.get("thermal_status_start"),
        "thermal_status_end": phase11.get("thermal_status_end"),
    }
    if estimator is not None:
        summary["alignment_states"] = sorted(map(str, estimator["alignment_state"].unique()))
        summary["final_localization_state"] = str(estimator.iloc[-1]["localization_state"])
    return summary


def _evaluate_blackout(
    number: int,
    start: int,
    end: int,
    runtime: pd.DataFrame,
    estimator: pd.DataFrame,
    reference: pd.DataFrame,
) -> tuple[dict[str, object], pd.DataFrame]:
    start_s = float(runtime.iloc[start]["elapsed_seconds"])
    end_s = float(runtime.iloc[end]["elapsed_seconds"])
    merged = estimator.merge(runtime[["sequence_id", "simulated_blackout"]], on="sequence_id", how="inner")
    segment = merged.loc[(merged["elapsed_seconds"] >= start_s) & (merged["elapsed_seconds"] <= end_s)].copy()
    ref_min = float(reference["elapsed_seconds"].min())
    ref_max = float(reference["elapsed_seconds"].max())
    segment = segment.loc[segment["elapsed_seconds"].between(ref_min, ref_max)].copy()
    if segment.empty:
        raise ValueError(f"Blackout {number} has no estimator/reference time overlap")
    times = segment["elapsed_seconds"].to_numpy(dtype=float)
    ref_times = reference["elapsed_seconds"].to_numpy(dtype=float)
    segment["reference_latitude_deg"] = np.interp(times, ref_times, reference["latitude_deg"])
    segment["reference_longitude_deg"] = np.interp(times, ref_times, reference["longitude_deg"])
    predicted_ok = segment[["estimated_latitude_deg", "estimated_longitude_deg"]].notna().all(axis=1)
    segment = segment.loc[predicted_ok].copy()
    if len(segment) < 2:
        raise ValueError(f"Blackout {number} has insufficient geodetic estimator output")
    errors = position_error_series_m(
        segment["estimated_latitude_deg"], segment["estimated_longitude_deg"],
        segment["reference_latitude_deg"], segment["reference_longitude_deg"],
    )
    segment["position_error_m"] = errors
    reference_distance = path_distance_m(segment["reference_latitude_deg"], segment["reference_longitude_deg"])
    error_metrics = summarize_position_errors(errors, reference_distance).to_dict()
    estimated_distance = path_distance_m(segment["estimated_latitude_deg"], segment["estimated_longitude_deg"])
    steps = great_circle_distance_m(
        segment["estimated_latitude_deg"].to_numpy()[:-1], segment["estimated_longitude_deg"].to_numpy()[:-1],
        segment["estimated_latitude_deg"].to_numpy()[1:], segment["estimated_longitude_deg"].to_numpy()[1:],
    )
    sigma = pd.to_numeric(segment["horizontal_uncertainty_m"], errors="coerce")
    ratio = errors / sigma.to_numpy(dtype=float)
    ratio = ratio[np.isfinite(ratio) & (sigma.to_numpy(dtype=float) > 0)]
    after = merged.loc[merged["elapsed_seconds"] > end_s].copy()
    restored = after.loc[after["localization_state"] == "GNSS_ACTIVE"]
    recovery_s = None if restored.empty else float(restored.iloc[0]["elapsed_seconds"] - end_s)
    post_error = None
    recovery_overshoot = None
    recovery_window = after.head(100).loc[
        after.head(100)["elapsed_seconds"].between(ref_min, ref_max)
        & after.head(100)[["estimated_latitude_deg", "estimated_longitude_deg"]].notna().all(axis=1)
    ]
    if not recovery_window.empty:
        recovery_times = recovery_window["elapsed_seconds"].to_numpy(dtype=float)
        recovery_errors = position_error_series_m(
            recovery_window["estimated_latitude_deg"], recovery_window["estimated_longitude_deg"],
            np.interp(recovery_times, ref_times, reference["latitude_deg"]),
            np.interp(recovery_times, ref_times, reference["longitude_deg"]),
        )
        recovery_overshoot = float(max(0.0, np.max(recovery_errors) - recovery_errors[0]))
    if not restored.empty:
        row = restored.iloc[0]
        t = float(row["elapsed_seconds"])
        if ref_min <= t <= ref_max and pd.notna(row["estimated_latitude_deg"]) and pd.notna(row["estimated_longitude_deg"]):
            lat = float(np.interp(t, ref_times, reference["latitude_deg"]))
            lon = float(np.interp(t, ref_times, reference["longitude_deg"]))
            post_error = float(great_circle_distance_m(row["estimated_latitude_deg"], row["estimated_longitude_deg"], lat, lon))
    ml = _fractions(segment["ml_state"])
    metrics: dict[str, object] = {
        "blackout_id": number,
        "start_elapsed_seconds": start_s,
        "end_elapsed_seconds": end_s,
        "blackout_duration_seconds": end_s - start_s,
        "evaluated_samples": len(segment),
        "estimated_distance_m": estimated_distance,
        **error_metrics,
        "maximum_estimator_step_m": float(np.max(steps)) if len(steps) else 0.0,
        "uncertainty_start_m": None if sigma.empty or pd.isna(sigma.iloc[0]) else float(sigma.iloc[0]),
        "uncertainty_end_m": None if sigma.empty or pd.isna(sigma.iloc[-1]) else float(sigma.iloc[-1]),
        "error_over_sigma_median": None if ratio.size == 0 else float(np.median(ratio)),
        "error_within_reported_sigma_fraction": None if ratio.size == 0 else float(np.mean(ratio <= 1.0)),
        "ml_state_fractions": ml,
        "localization_states": sorted(map(str, segment["localization_state"].unique())),
        "alignment_states": sorted(map(str, segment["alignment_state"].unique())),
        "recovery_duration_seconds": recovery_s,
        "recovery_max_correction_m": _safe_stat(after.head(100)["last_correction_m"], "max"),
        "recovery_position_overshoot_m": recovery_overshoot,
        "post_recovery_position_error_m": post_error,
        "ml_ood_exceedance_median": _safe_stat(segment["ml_ood_exceedance"], "median"),
        "ml_ood_exceedance_maximum": _safe_stat(segment["ml_ood_exceedance"], "max"),
        "ml_residual_correction_mean_mps": _safe_stat(segment["ml_residual_mps"].abs(), "mean"),
        "ml_residual_correction_maximum_mps": _safe_stat(segment["ml_residual_mps"].abs(), "max"),
    }
    return metrics, segment


def _write_outputs(result: SessionValidationResult, audit: pd.DataFrame, samples: list[pd.DataFrame]) -> None:
    output = result.output_directory
    assert output is not None
    output.mkdir(parents=True, exist_ok=True)
    (output / "phase11_validation.json").write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
    pd.json_normalize(result.blackout_metrics, sep=".").to_csv(output / "blackout_metrics.csv", index=False)
    audit.to_csv(output / "reference_quality_audit.csv", index=False)
    report = [
        "# Phase 11 Android field validation",
        "",
        f"Session: `{result.session_id}`",
        f"Status: **{'EVALUABLE' if result.evaluable else 'NOT EVALUABLE'}**",
        f"Reference: {result.reference_wording}. This is not survey-grade ground truth.",
        "",
        f"Reference quality: {result.quality.retained_points}/{result.quality.total_points} points retained.",
        f"Device: {result.session_summary.get('device') or 'N/A'}  ",
        f"Session duration: {result.session_summary.get('duration_seconds', 'N/A')} s  ",
        f"Engine average / P95: {result.session_summary.get('engine_average_ms') or 'N/A'} / {result.session_summary.get('engine_p95_ms') or 'N/A'} ms  ",
        f"Battery start / end: {result.session_summary.get('battery_start_percent') or 'N/A'} / {result.session_summary.get('battery_end_percent') or 'N/A'} %",
        "",
    ]
    for metric in result.blackout_metrics:
        report += [
            f"## Blackout {metric['blackout_id']}",
            "",
            f"Duration: {metric['blackout_duration_seconds']:.2f} s  ",
            f"Reference distance: {metric['reference_distance_m']:.2f} m  ",
            f"Final error: {metric['final_position_error_m']:.2f} m  ",
            f"RMSE: {metric['rmse_position_error_m']:.2f} m  ",
            f"P95: {metric['p95_position_error_m']:.2f} m  ",
            f"Drift: {metric['drift_percentage'] if metric['drift_percentage'] is not None else 'N/A'} %",
            "",
        ]
    report += ["## Limitations", "", *[f"- {item}" for item in result.limitations]]
    (output / "PHASE11_FIELD_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    for metric, sample in zip(result.blackout_metrics, samples, strict=True):
        number = metric["blackout_id"]
        fig, axis = plt.subplots(figsize=(6.8, 5.2))
        axis.plot(sample["reference_longitude_deg"], sample["reference_latitude_deg"], label="phone-GNSS evaluation reference")
        axis.plot(sample["estimated_longitude_deg"], sample["estimated_latitude_deg"], label="IDR estimate")
        axis.set_title(f"Blackout {number}: evaluator-only comparison")
        axis.set_xlabel("longitude (deg)"); axis.set_ylabel("latitude (deg)"); axis.legend(); axis.grid(alpha=0.25)
        fig.tight_layout(); fig.savefig(output / f"blackout_{number}_trajectory.png", dpi=150); plt.close(fig)
        fig, axis = plt.subplots(figsize=(7.2, 3.6))
        axis.plot(sample["elapsed_seconds"], sample["position_error_m"], label="position error")
        axis.plot(sample["elapsed_seconds"], sample["horizontal_uncertainty_m"], label="engineering uncertainty")
        axis.set_xlabel("session elapsed time (s)"); axis.set_ylabel("metres"); axis.legend(); axis.grid(alpha=0.25)
        fig.tight_layout(); fig.savefig(output / f"blackout_{number}_error_uncertainty.png", dpi=150); plt.close(fig)


def validate_android_session(
    session_directory: str | Path,
    *,
    reference_path: str | Path | None = None,
    output_directory: str | Path | None = None,
    write_outputs: bool = True,
) -> SessionValidationResult:
    """Validate a field session without exposing evaluator GNSS to runtime code."""

    root = Path(session_directory).resolve()
    session = load_android_session(root)
    reference, quality, audit = load_evaluation_reference(root, reference_path)
    try:
        estimator = load_android_idr_output(root)
    except AndroidIdrOutputError as error:
        output = None
        if write_outputs:
            output = Path(output_directory).resolve() if output_directory else root / "phase11_validation"
        result = SessionValidationResult(
            session.session_id,
            False,
            quality.source,
            quality,
            _session_summary(session, None),
            (),
            output,
            (
                str(error),
                "This recording predates or lacks Phase 10/11 estimator output and is not a road-accuracy experiment.",
            ),
        )
        if write_outputs:
            _write_outputs(result, audit, [])
        return result
    if not np.array_equal(session.runtime["sequence_id"].to_numpy(), estimator["sequence_id"].to_numpy()):
        raise ValueError("Runtime and estimator sequence IDs are not exactly aligned")
    blackout_groups = _groups(session.runtime["simulated_blackout"].to_numpy(dtype=bool))
    limitations = [
        "Phone GNSS is a same-device evaluation proxy, not absolute or survey-grade truth."
        if reference_path is None else "Independent reference quality depends on the supplied logger and synchronization.",
        "Reference interpolation is non-causal and evaluator-only; it never enters the Android estimator.",
        "Reported uncertainty is engineering covariance, not a calibrated 95% confidence interval.",
    ]
    evaluable = len(reference) >= 2 and bool(blackout_groups)
    metrics: list[dict[str, object]] = []
    samples: list[pd.DataFrame] = []
    if evaluable:
        for number, (start, end) in enumerate(blackout_groups, 1):
            try:
                metric, sample = _evaluate_blackout(number, start, end, session.runtime, estimator, reference)
            except ValueError as error:
                limitations.append(str(error))
            else:
                metrics.append(metric); samples.append(sample)
        evaluable = bool(metrics)
    if not blackout_groups:
        limitations.append("No simulated-blackout interval exists in runtime_10hz.csv.")
    if len(reference) < 2:
        limitations.append("Fewer than two usable evaluation-reference points remain after quality gating.")
    output = None
    if write_outputs:
        output = Path(output_directory).resolve() if output_directory else root / "phase11_validation"
    result = SessionValidationResult(
        session.session_id, evaluable, quality.source, quality, _session_summary(session, estimator),
        tuple(metrics), output, tuple(limitations),
    )
    if write_outputs:
        _write_outputs(result, audit, samples)
    return result
