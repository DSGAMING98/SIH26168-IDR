#!/usr/bin/env python3
"""Run the frozen Phase 5 Raw/Phase4/EKF/Hybrid held-out comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import torch  # noqa: E402

from idr.blackout import BlackoutWindow  # noqa: E402
from idr.calibrated_dr import Phase4Settings  # noqa: E402
from idr.hybrid.hybrid_idr import HybridSettings  # noqa: E402
from idr.io_vnbd import load_journey, sha256_file  # noqa: E402
from idr.ml.velocity_model import load_velocity_bundle  # noqa: E402
from idr.phase5_pipeline import Phase5ScenarioRun, run_phase5_scenario  # noqa: E402


COLORS = {
    "reference": "#222222",
    "raw": "#D55E00",
    "v4": "#E69F00",
    "v5": "#CC79A7",
    "ekf": "#0072B2",
    "hybrid": "#009E73",
}


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate.resolve() if candidate.is_absolute() else (ROOT / candidate).resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, np.bool_):
        return bool(value)
    raise TypeError(f"Cannot serialize {type(value)!r}")


def _save_figure(figure: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def _style(axis: Any) -> None:
    axis.grid(True, alpha=0.23, linewidth=0.7)
    axis.spines[["top", "right"]].set_visible(False)


def _verify_frozen(result_dir: Path, paths: dict[str, Path], checkpoint: Path) -> dict[str, Any]:
    frozen_path = result_dir / "frozen_configuration.json"
    if not frozen_path.exists():
        raise FileNotFoundError("Train/freeze the velocity model before benchmark execution.")
    frozen = _json(frozen_path)
    for name, path in paths.items():
        expected = frozen["config_sha256"][name]
        actual = _sha256(path)
        if expected != actual:
            raise RuntimeError(f"Frozen {name} configuration changed before benchmark execution.")
    if frozen["checkpoint_sha256"] != _sha256(checkpoint):
        raise RuntimeError("Frozen velocity checkpoint changed before benchmark execution.")
    return frozen


def _combined_timeseries(run: Phase5ScenarioRun) -> pd.DataFrame:
    raw = run.raw_evaluation.timeseries
    v4 = run.phase4_v4_evaluation.timeseries
    v5 = run.phase4_v5_evaluation.timeseries
    ekf = run.ekf_evaluation.timeseries
    hybrid = run.hybrid_evaluation.timeseries
    result = pd.DataFrame(
        {
            "elapsed_s": raw["elapsed_s"],
            "blackout_elapsed_s": raw["blackout_elapsed_s"],
            "reference_relative_x_m": raw["reference_relative_x_m"],
            "reference_relative_y_m": raw["reference_relative_y_m"],
            "reference_speed_mps": raw["reference_speed_mps"],
        }
    )
    for prefix, evaluation in (
        ("raw", raw),
        ("phase4_v4", v4),
        ("phase4_v5", v5),
        ("ekf", ekf),
        ("hybrid", hybrid),
    ):
        result[f"{prefix}_relative_x_m"] = evaluation["predicted_relative_x_m"]
        result[f"{prefix}_relative_y_m"] = evaluation["predicted_relative_y_m"]
        result[f"{prefix}_position_error_m"] = evaluation["relative_position_error_m"]
        result[f"{prefix}_speed_mps"] = evaluation["estimated_speed_mps"]
    for field in (
        "ml_speed_measurement_mps",
        "ml_predicted_residual_mps",
        "ml_update_attempted",
        "ml_update_accepted",
        "ml_update_rejected_innovation",
        "ml_update_skipped_ood",
        "ml_normalized_innovation_squared",
        "stationary_update_attempted",
        "stationary_update_accepted",
        "horizontal_position_sigma_m",
    ):
        result[field] = hybrid[field]
    return result


def _scenario_plots(scenario_id: str, timeseries: pd.DataFrame, plots_dir: Path) -> dict[str, str]:
    slug = scenario_id.lower()
    paths = {
        "trajectory": plots_dir / f"{slug}_trajectory_comparison.png",
        "error": plots_dir / f"{slug}_position_error.png",
        "speed": plots_dir / f"{slug}_speed_comparison.png",
        "uncertainty": plots_dir / f"{slug}_uncertainty.png",
        "innovation": plots_dir / f"{slug}_innovation_updates.png",
    }
    figure, axis = plt.subplots(figsize=(8.0, 7.0))
    axis.plot(timeseries["reference_relative_x_m"], timeseries["reference_relative_y_m"], color=COLORS["reference"], linewidth=2.0, label="VBOX evaluation reference only")
    for prefix, label, width in (
        ("raw", "Phase 3 Raw", 1.0),
        ("phase4_v4", "Phase 4 V4", 1.2),
        ("ekf", "Classical EKF", 1.3),
        ("hybrid", "Hybrid EKF + ML", 1.7),
    ):
        axis.plot(timeseries[f"{prefix}_relative_x_m"], timeseries[f"{prefix}_relative_y_m"], color=COLORS[prefix.replace("phase4_", "")], linewidth=width, label=label)
    axis.scatter(0.0, 0.0, color="#111111", s=35, marker="o", label="Blackout start", zorder=5)
    axis.scatter(timeseries["reference_relative_x_m"].iloc[-1], timeseries["reference_relative_y_m"].iloc[-1], color=COLORS["reference"], s=55, marker="X", zorder=5)
    axis.scatter(timeseries["hybrid_relative_x_m"].iloc[-1], timeseries["hybrid_relative_y_m"].iloc[-1], color=COLORS["hybrid"], s=55, marker="X", zorder=5)
    axis.set(title=f"{scenario_id}: held-out trajectory", xlabel="East displacement (m)", ylabel="North displacement (m)")
    axis.set_aspect("equal", adjustable="datalim")
    axis.legend(frameon=False, fontsize=8)
    _style(axis)
    _save_figure(figure, paths["trajectory"])

    figure, axis = plt.subplots(figsize=(9.5, 4.8))
    for prefix, label in (("raw", "Raw"), ("phase4_v4", "Phase 4 V4"), ("ekf", "EKF"), ("hybrid", "Hybrid")):
        axis.plot(timeseries["blackout_elapsed_s"], timeseries[f"{prefix}_position_error_m"], color=COLORS[prefix.replace("phase4_", "")], label=label)
    axis.set(title=f"{scenario_id}: position error growth", xlabel="Blackout time (s)", ylabel="Relative position error (m)")
    axis.legend(frameon=False, ncol=4)
    _style(axis)
    _save_figure(figure, paths["error"])

    figure, axis = plt.subplots(figsize=(9.5, 4.8))
    axis.plot(timeseries["blackout_elapsed_s"], timeseries["reference_speed_mps"], color=COLORS["reference"], label="VBOX evaluation reference only")
    axis.plot(timeseries["blackout_elapsed_s"], timeseries["phase4_v4_speed_mps"], color=COLORS["v4"], label="Phase 4 V4")
    axis.plot(timeseries["blackout_elapsed_s"], timeseries["ekf_speed_mps"], color=COLORS["ekf"], label="Classical EKF")
    axis.plot(timeseries["blackout_elapsed_s"], timeseries["ml_speed_measurement_mps"], color="#56B4E9", alpha=0.65, label="ML pseudo-measurement")
    axis.plot(timeseries["blackout_elapsed_s"], timeseries["hybrid_speed_mps"], color=COLORS["hybrid"], linewidth=1.5, label="Hybrid speed")
    axis.set(title=f"{scenario_id}: speed during blackout", xlabel="Blackout time (s)", ylabel="Speed (m/s)")
    axis.legend(frameon=False, ncol=3, fontsize=8)
    _style(axis)
    _save_figure(figure, paths["speed"])

    figure, axis = plt.subplots(figsize=(9.5, 4.5))
    axis.plot(timeseries["blackout_elapsed_s"], timeseries["horizontal_position_sigma_m"], color=COLORS["hybrid"])
    axis.set(title=f"{scenario_id}: estimated position uncertainty", xlabel="Blackout time (s)", ylabel="sqrt(Pxx + Pyy) (m)")
    _style(axis)
    _save_figure(figure, paths["uncertainty"])

    figure, axes = plt.subplots(2, 1, figsize=(9.5, 6.0), sharex=True)
    attempted = timeseries["ml_update_attempted"].to_numpy(dtype=bool)
    accepted = timeseries["ml_update_accepted"].to_numpy(dtype=bool)
    rejected = attempted & ~accepted
    axes[0].plot(timeseries["blackout_elapsed_s"], timeseries["ml_normalized_innovation_squared"], color=COLORS["ekf"], linewidth=0.9, label="ML speed NIS")
    axes[0].axhline(9.0, color="#777777", linestyle="--", linewidth=0.9, label="Frozen gate")
    axes[0].legend(frameon=False, fontsize=8)
    axes[0].set_ylabel("NIS")
    axes[1].scatter(timeseries.loc[accepted, "blackout_elapsed_s"], np.ones(int(accepted.sum())), color=COLORS["hybrid"], s=9, label="Accepted ML")
    axes[1].scatter(timeseries.loc[rejected, "blackout_elapsed_s"], np.zeros(int(rejected.sum())), color=COLORS["raw"], s=12, marker="x", label="Rejected/skipped ML")
    stationary = timeseries["stationary_update_accepted"].to_numpy(dtype=bool)
    axes[1].scatter(timeseries.loc[stationary, "blackout_elapsed_s"], np.full(int(stationary.sum()), 2.0), color=COLORS["v4"], s=9, label="Stationary update")
    axes[1].set(yticks=[0, 1, 2], yticklabels=["rejected", "accepted", "stationary"], xlabel="Blackout time (s)")
    axes[1].legend(frameon=False, fontsize=8, ncol=3)
    for axis in axes:
        _style(axis)
    axes[0].set_title(f"{scenario_id}: innovation and update diagnostic", loc="left")
    _save_figure(figure, paths["innovation"])
    plot_paths = {}
    for key, path in paths.items():
        try:
            display_path = path.relative_to(ROOT)
        except ValueError:
            display_path = path.resolve()
        plot_paths[key] = str(display_path).replace("\\", "/")
    return plot_paths


def _metric(metrics: dict[str, Any], name: str) -> float:
    return float(metrics[name])


def _scenario_summary(scenario: dict[str, Any], run: Phase5ScenarioRun) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    metrics = {
        "B0_RAW": run.raw_evaluation.metrics,
        "B1_PHASE4_V4": run.phase4_v4_evaluation.metrics,
        "B2_PHASE4_V5": run.phase4_v5_evaluation.metrics,
        "E1_EKF_CLASSICAL": run.ekf_evaluation.metrics,
        "H1_HYBRID_EKF_ML": run.hybrid_evaluation.metrics,
    }
    v4_error = _metric(metrics["B1_PHASE4_V4"], "final_position_error_m")
    v5_error = _metric(metrics["B2_PHASE4_V5"], "final_position_error_m")
    best_phase4_key = "B1_PHASE4_V4" if v4_error <= v5_error else "B2_PHASE4_V5"
    hybrid_error = _metric(metrics["H1_HYBRID_EKF_ML"], "final_position_error_m")
    raw_error = _metric(metrics["B0_RAW"], "final_position_error_m")
    best_phase4_error = _metric(metrics[best_phase4_key], "final_position_error_m")
    row = {
        "scenario": scenario["id"],
        "scenario_type": scenario["type"],
        "standard": bool(scenario.get("standard", False)),
        "surprise_holdout": bool(scenario.get("surprise_holdout", False)),
        "start_s": float(scenario["start_s"]),
        "duration_s": float(scenario["duration_s"]),
        "actual_duration_s": run.experiment.metadata.actual_masked_duration_s,
        "sample_count": run.experiment.metadata.masked_sample_count,
        "reference_distance_m": _metric(metrics["B0_RAW"], "reference_distance_m"),
        "raw_drift_pct": _metric(metrics["B0_RAW"], "drift_percentage"),
        "phase4_v4_drift_pct": _metric(metrics["B1_PHASE4_V4"], "drift_percentage"),
        "phase4_v5_drift_pct": _metric(metrics["B2_PHASE4_V5"], "drift_percentage"),
        "ekf_drift_pct": _metric(metrics["E1_EKF_CLASSICAL"], "drift_percentage"),
        "hybrid_drift_pct": _metric(metrics["H1_HYBRID_EKF_ML"], "drift_percentage"),
        "raw_final_error_m": raw_error,
        "phase4_v4_final_error_m": v4_error,
        "phase4_v5_final_error_m": v5_error,
        "phase4_best_variant": best_phase4_key,
        "phase4_best_final_error_m": best_phase4_error,
        "ekf_final_error_m": _metric(metrics["E1_EKF_CLASSICAL"], "final_position_error_m"),
        "hybrid_final_error_m": hybrid_error,
        "hybrid_improvement_vs_raw_pct": (raw_error - hybrid_error) / raw_error * 100.0,
        "hybrid_improvement_vs_phase4_best_pct": (best_phase4_error - hybrid_error) / best_phase4_error * 100.0,
        "hybrid_rmse_m": _metric(metrics["H1_HYBRID_EKF_ML"], "rmse_position_error_m"),
        "hybrid_p95_m": _metric(metrics["H1_HYBRID_EKF_ML"], "p95_position_error_m"),
        "hybrid_speed_mae_mps": _metric(metrics["H1_HYBRID_EKF_ML"], "speed_mae_mps"),
        "hybrid_speed_rmse_mps": _metric(metrics["H1_HYBRID_EKF_ML"], "speed_rmse_mps"),
        "hybrid_final_uncertainty_m": _metric(metrics["H1_HYBRID_EKF_ML"], "final_position_uncertainty_m"),
        "hybrid_mean_uncertainty_m": _metric(metrics["H1_HYBRID_EKF_ML"], "mean_position_uncertainty_m"),
        "ml_updates_accepted": int(metrics["H1_HYBRID_EKF_ML"]["ml_updates_accepted"]),
        "ml_updates_rejected_innovation": int(metrics["H1_HYBRID_EKF_ML"]["ml_updates_rejected_innovation"]),
        "ml_updates_skipped_ood": int(metrics["H1_HYBRID_EKF_ML"]["ml_updates_skipped_ood"]),
    }
    ablations = []
    for algorithm, values in metrics.items():
        ablations.append(
            {
                "scenario": scenario["id"],
                "algorithm": algorithm,
                "final_error_m": _metric(values, "final_position_error_m"),
                "mean_error_m": _metric(values, "mean_position_error_m"),
                "rmse_m": _metric(values, "rmse_position_error_m"),
                "p95_m": _metric(values, "p95_position_error_m"),
                "drift_pct": _metric(values, "drift_percentage"),
                "speed_mae_mps": values.get("speed_mae_mps"),
                "speed_rmse_mps": values.get("speed_rmse_mps"),
            }
        )
    return row, ablations


def _drift_plot(summary: pd.DataFrame, path: Path) -> None:
    fields = (
        ("raw_drift_pct", "Raw", "raw"),
        ("phase4_v4_drift_pct", "Phase 4 V4", "v4"),
        ("phase4_v5_drift_pct", "Phase 4 V5", "v5"),
        ("ekf_drift_pct", "EKF", "ekf"),
        ("hybrid_drift_pct", "Hybrid", "hybrid"),
    )
    x = np.arange(len(summary), dtype=float)
    width = 0.15
    figure, axis = plt.subplots(figsize=(12, 5.8))
    for index, (field, label, color) in enumerate(fields):
        axis.bar(x + (index - 2) * width, summary[field], width, label=label, color=COLORS[color])
    axis.axhline(10.0, color="#555555", linestyle="--", linewidth=1.0, label="SIH 10% target")
    axis.set_xticks(x, [str(value).replace("S1_", "") for value in summary["scenario"]], rotation=10)
    axis.set(title="Held-out blackout drift comparison", ylabel="Drift (%)")
    axis.legend(frameon=False, ncol=6, fontsize=8)
    _style(axis)
    _save_figure(figure, path)


def _judge_summary(summary: pd.DataFrame, frozen: dict[str, Any], performance: dict[str, Any]) -> str:
    rows = [
        "# Phase 5 Judge Summary",
        "",
        "Phase 3 raw integration drifted because small phone acceleration and orientation errors accumulated twice into position. Phase 4 added gravity alignment, causal conditioning, gyro course, calibration, and conservative motion constraints.",
        "",
        "Phase 5 adds a covariance-aware six-state EKF and a 4,257-parameter GRU that predicts only a bounded speed residual. Position is still propagated by the physical EKF. VBOX supplies offline training labels and evaluation only; it is not an estimator input.",
        "",
        "All five named holdouts plus the surprise window were quarantined from training, validation, scaling, checkpoint selection, and EKF tuning using 120 seconds before each blackout and 60 seconds after its end.",
        "",
        "| Scenario | Raw drift | P4 V4 | P4 V5 | EKF | Hybrid | Hybrid final error | Est. uncertainty |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary.itertuples(index=False):
        rows.append(
            f"| {row.scenario} | {row.raw_drift_pct:.2f}% | {row.phase4_v4_drift_pct:.2f}% | {row.phase4_v5_drift_pct:.2f}% | {row.ekf_drift_pct:.2f}% | {row.hybrid_drift_pct:.2f}% | {row.hybrid_final_error_m:.2f} m | {row.hybrid_final_uncertainty_m:.2f} m |"
        )
    rows.extend(
        [
            "",
            f"The frozen checkpoint is {frozen['checkpoint_size_bytes']:,} bytes and the complete measured pipeline processed {performance['hybrid_samples_per_second']:.1f} samples/s versus a 10 Hz input rate.",
            "",
            "The uncertainty is an interpretable covariance-derived estimate (`sqrt(Pxx + Pyy)`), not a statistically calibrated 95% bound. Remaining road-constrained error and single-journey generalization are Phase 6/later limitations; no map matching or Android application is implemented here.",
        ]
    )
    return "\n".join(rows) + "\n"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", help="Run one configured scenario ID.")
    parser.add_argument("--session", default="S1")
    parser.add_argument("--start", type=float)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--scenario-id")
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.scenario and (args.start is not None or args.duration is not None):
        raise SystemExit("--scenario cannot be combined with --start/--duration.")
    if (args.start is None) != (args.duration is None):
        raise SystemExit("Custom execution requires both --start and --duration.")
    hybrid_path = ROOT / "configs" / "phase5" / "io_vnbd_s1_hybrid.json"
    hybrid_config = _json(hybrid_path)
    phase4_path = _resolve(hybrid_config["phase4_config"])
    split_path = _resolve(hybrid_config["split_config"])
    ml_path = _resolve(hybrid_config["ml_config"])
    ekf_path = _resolve(hybrid_config["ekf_config"])
    checkpoint = _resolve(hybrid_config["checkpoint_path"])
    canonical_result_dir = ROOT / "results" / "phase5" / "io_vnbd" / "s1"
    frozen = _verify_frozen(
        canonical_result_dir,
        {"ml": ml_path, "split": split_path, "phase4": phase4_path, "ekf": ekf_path},
        checkpoint,
    )
    benchmark = _json(_resolve(hybrid_config["blackout_config"]))
    phase4_config = _json(phase4_path)
    split = _json(split_path)
    scenarios = [dict(item) for item in benchmark["scenarios"] if item.get("standard")]
    scenarios.append(dict(phase4_config["custom_judge_scenario"]))
    surprise = next(item for item in split["quarantine_intervals"] if item["id"] == "S1_PHASE5_SURPRISE")
    scenarios.append(
        {
            "id": "S1_PHASE5_SURPRISE",
            "start_s": surprise["blackout_start_s"],
            "duration_s": surprise["duration_s"],
            "type": "preselected_surprise_holdout",
            "standard": False,
            "surprise_holdout": True,
        }
    )
    selected_run = bool(args.scenario or args.start is not None)
    if args.start is not None:
        scenarios = [
            {
                "id": args.scenario_id or f"{args.session}_{float(args.duration):g}_PHASE5_CUSTOM",
                "start_s": float(args.start),
                "duration_s": float(args.duration),
                "type": "custom_phase5",
                "standard": False,
            }
        ]
    elif args.scenario:
        scenarios = [item for item in scenarios if item["id"].upper() == args.scenario.upper()]
        if not scenarios:
            raise SystemExit(f"Scenario not found: {args.scenario}")
    if args.output_dir:
        output_dir = _resolve(args.output_dir)
    elif selected_run:
        output_dir = canonical_result_dir / "reproductions" / str(scenarios[0]["id"]).lower()
    else:
        output_dir = canonical_result_dir
    plots_dir = output_dir / "plots"
    scenarios_dir = output_dir / "scenarios"
    for directory in (output_dir, plots_dir, scenarios_dir, output_dir / "ekf", output_dir / "hybrid", output_dir / "ablations"):
        directory.mkdir(parents=True, exist_ok=True)

    journey = load_journey(args.session, project_root_path=ROOT)
    source_before = {
        "smartphone": sha256_file(journey.smartphone_path),
        "vbox_reference": sha256_file(journey.vehicle_path),
    }
    phase4_settings = Phase4Settings.from_dict(phase4_config)
    hybrid_settings = HybridSettings.from_dict(_json(ekf_path))
    bundle = load_velocity_bundle(checkpoint)
    summary_rows: list[dict[str, Any]] = []
    ablation_rows: list[dict[str, Any]] = []
    scenario_payloads: list[dict[str, Any]] = []
    estimator_samples = 0
    ekf_seconds = 0.0
    hybrid_seconds = 0.0
    inference_window = None
    for scenario in scenarios:
        run = run_phase5_scenario(
            journey,
            BlackoutWindow(float(scenario["start_s"]), float(scenario["duration_s"])),
            phase4_settings,
            hybrid_settings,
            bundle,
        )
        summary, ablations = _scenario_summary(scenario, run)
        summary_rows.append(summary)
        ablation_rows.extend(ablations)
        combined = _combined_timeseries(run)
        scenario_dir = scenarios_dir / str(scenario["id"]).lower()
        scenario_dir.mkdir(parents=True, exist_ok=True)
        combined.to_csv(scenario_dir / "timeseries.csv", index=False)
        plot_paths = _scenario_plots(str(scenario["id"]), combined, plots_dir)
        payload = {
            "scenario": scenario,
            "blackout_metadata": run.experiment.metadata.to_dict(),
            "summary": summary,
            "metrics": {
                "raw": run.raw_evaluation.metrics,
                "phase4_v4": run.phase4_v4_evaluation.metrics,
                "phase4_v5": run.phase4_v5_evaluation.metrics,
                "ekf": run.ekf_evaluation.metrics,
                "hybrid": run.hybrid_evaluation.metrics,
            },
            "processing_seconds": run.processing_seconds,
            "plots": plot_paths,
        }
        (scenario_dir / "result.json").write_text(
            json.dumps(payload, indent=2, default=_json_default) + "\n", encoding="utf-8"
        )
        scenario_payloads.append(payload)
        estimator_samples += run.experiment.metadata.masked_sample_count
        ekf_seconds += run.processing_seconds["ekf"]
        hybrid_seconds += run.processing_seconds["hybrid"]
        if inference_window is None and len(run.hybrid_prediction.feature_data) >= bundle.config.window_steps:
            inference_window = run.hybrid_prediction.feature_data.iloc[: bundle.config.window_steps].to_numpy(dtype=np.float32)

    summary_frame = pd.DataFrame(summary_rows)
    ablation_frame = pd.DataFrame(ablation_rows)
    summary_frame.to_csv(output_dir / "summary.csv", index=False)
    (output_dir / "summary.json").write_text(
        json.dumps(summary_rows, indent=2, default=_json_default) + "\n", encoding="utf-8"
    )
    ekf_columns = [column for column in summary_frame.columns if column.startswith("ekf_") or column in {"scenario", "duration_s", "reference_distance_m"}]
    hybrid_columns = [column for column in summary_frame.columns if column.startswith("hybrid_") or column in {"scenario", "duration_s", "reference_distance_m"}]
    summary_frame[ekf_columns].to_csv(output_dir / "ekf" / "summary.csv", index=False)
    summary_frame[hybrid_columns].to_csv(output_dir / "hybrid" / "summary.csv", index=False)
    (output_dir / "ekf" / "summary.json").write_text(summary_frame[ekf_columns].to_json(orient="records", indent=2) + "\n", encoding="utf-8")
    (output_dir / "hybrid" / "summary.json").write_text(summary_frame[hybrid_columns].to_json(orient="records", indent=2) + "\n", encoding="utf-8")
    ablation_frame.to_csv(output_dir / "ablations" / "ablation.csv", index=False)
    (output_dir / "ablations" / "ablation.json").write_text(ablation_frame.to_json(orient="records", indent=2) + "\n", encoding="utf-8")
    _drift_plot(summary_frame, plots_dir / "drift_comparison.png")

    assert inference_window is not None
    repetitions = 1000
    started = time.perf_counter()
    for _ in range(repetitions):
        bundle.predict_window(inference_window)
    ml_seconds = time.perf_counter() - started
    performance = {
        "input_rate_hz": 10.0,
        "ekf_samples_per_second": estimator_samples / ekf_seconds,
        "hybrid_samples_per_second": estimator_samples / hybrid_seconds,
        "ml_inference_windows_per_second": repetitions / ml_seconds,
        "ml_average_latency_ms": ml_seconds / repetitions * 1000.0,
        "model_parameter_bytes_float32": frozen["parameter_count"] * 4,
        "checkpoint_size_bytes": checkpoint.stat().st_size,
    }
    source_after = {
        "smartphone": sha256_file(journey.smartphone_path),
        "vbox_reference": sha256_file(journey.vehicle_path),
    }
    if source_before != source_after:
        raise RuntimeError("Original dataset checksum changed during Phase 5 execution.")
    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "phase": 5,
        "session": journey.session_id,
        "benchmark_execution_after_freeze": True,
        "frozen_configuration": frozen,
        "same_configuration_all_scenarios": True,
        "scenario_ids": [item["id"] for item in scenarios],
        "source_checksums_before_and_after_match": True,
        "source_sha256": source_after,
        "performance": performance,
        "python": sys.version,
        "platform": platform.platform(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "torch": torch.__version__,
        "git_head_at_execution": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip(),
        "results": scenario_payloads,
    }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=_json_default) + "\n", encoding="utf-8"
    )
    if not selected_run:
        judge_path = ROOT / "results" / "phase5" / "PHASE5_JUDGE_SUMMARY.md"
        judge_path.parent.mkdir(parents=True, exist_ok=True)
        judge_path.write_text(_judge_summary(summary_frame, frozen, performance), encoding="utf-8")
    print(summary_frame.to_string(index=False))
    print(json.dumps(performance, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
