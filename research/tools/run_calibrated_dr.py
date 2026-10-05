#!/usr/bin/env python3
"""Run Phase 4 calibrated classical DR and its frozen V0-V5 ablations."""

from __future__ import annotations

import argparse
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
sys.path.insert(0, str(ROOT / ".deps"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from idr.attitude import gravity_euler_diagnostics  # noqa: E402
from idr.blackout import BlackoutWindow, create_blackout_experiment  # noqa: E402
from idr.calibrated_dr import (  # noqa: E402
    PHASE4_ALGORITHM,
    PHASE4_VARIANTS,
    Phase4Settings,
    as_raw_prediction,
    build_phase4_calibration,
    integrate_calibrated_dead_reckoning,
    phase4_sensor_diagnostics,
)
from idr.dead_reckoning import (  # noqa: E402
    build_phone_initialization,
    extract_blackout_sensor_data,
    integrate_raw_dead_reckoning,
)
from idr.io_vnbd import load_journey, sha256_file  # noqa: E402
from idr.raw_dr_evaluation import evaluate_raw_dr_prediction  # noqa: E402


V0 = "V0_RAW_PHASE3"
ALL_VARIANTS = (V0, *PHASE4_VARIANTS)
COLORS = {
    "reference": "#0072B2",
    "raw": "#D55E00",
    "phase4": "#009E73",
    "orientation": "#CC79A7",
    "gyro": "#E69F00",
    "grid": "#D9DEE5",
}


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT)).replace("\\", "/")


def _style(axis: Any) -> None:
    axis.grid(True, color=COLORS["grid"], linewidth=0.6, alpha=0.8)
    axis.spines[["top", "right"]].set_visible(False)


def _save(figure: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def _improvement(raw: dict[str, Any], candidate: dict[str, Any]) -> dict[str, float]:
    def change(key: str) -> float:
        baseline = float(raw[key])
        return float((baseline - float(candidate[key])) / baseline * 100.0)

    return {
        "final_error_improvement_pct": change("final_position_error_m"),
        "rmse_improvement_pct": change("rmse_position_error_m"),
        "drift_improvement_pct": change("drift_percentage"),
    }


def _plot_scenario(
    scenario_id: str,
    raw: pd.DataFrame,
    final: pd.DataFrame,
    blackout: pd.DataFrame,
    output_dir: Path,
) -> dict[str, str]:
    slug = scenario_id.lower()
    paths = {
        "trajectory": output_dir / "plots" / f"{slug}_raw_vs_phase4_trajectory.png",
        "error": output_dir / "plots" / f"{slug}_raw_vs_phase4_error.png",
        "heading": output_dir / "plots" / f"{slug}_heading_diagnostic.png",
        "speed": output_dir / "plots" / f"{slug}_speed_diagnostic.png",
        "acceleration": output_dir / "plots" / f"{slug}_acceleration_conditioning.png",
        "orientation": output_dir / "plots" / f"{slug}_orientation_sanity.png",
    }
    figure, axis = plt.subplots(figsize=(8.2, 7.0))
    axis.plot(raw["reference_relative_x_m"], raw["reference_relative_y_m"], color=COLORS["reference"], linewidth=2.0, label="VBOX reference - evaluation only")
    axis.plot(raw["predicted_relative_x_m"], raw["predicted_relative_y_m"], color=COLORS["raw"], linewidth=1.3, label="V0 raw Phase 3")
    axis.plot(final["predicted_relative_x_m"], final["predicted_relative_y_m"], color=COLORS["phase4"], linewidth=1.6, label="V5 Phase 4 combined")
    axis.scatter(0.0, 0.0, color="#222222", marker="o", s=45, label="Blackout start", zorder=6)
    axis.scatter(raw["reference_relative_x_m"].iloc[-1], raw["reference_relative_y_m"].iloc[-1], color=COLORS["reference"], marker="X", s=65, label="Reference end", zorder=6)
    axis.scatter(final["predicted_relative_x_m"].iloc[-1], final["predicted_relative_y_m"].iloc[-1], color=COLORS["phase4"], marker="X", s=65, label="Phase 4 end", zorder=6)
    axis.set_title(f"{scenario_id}: raw vs calibrated trajectory", loc="left", weight="bold")
    axis.set_xlabel("East displacement (m)")
    axis.set_ylabel("North displacement (m)")
    axis.set_aspect("equal", adjustable="datalim")
    axis.legend(frameon=False, fontsize=8)
    _style(axis)
    _save(figure, paths["trajectory"])

    figure, axis = plt.subplots(figsize=(9.5, 4.8))
    axis.plot(raw["blackout_elapsed_s"], raw["relative_position_error_m"], color=COLORS["raw"], label="V0 raw")
    axis.plot(final["blackout_elapsed_s"], final["relative_position_error_m"], color=COLORS["phase4"], label="V5 combined")
    axis.set_title(f"{scenario_id}: relative error growth", loc="left", weight="bold")
    axis.set_xlabel("Elapsed blackout time (s)")
    axis.set_ylabel("Relative position error (m)")
    axis.legend(frameon=False)
    _style(axis)
    _save(figure, paths["error"])

    figure, axis = plt.subplots(figsize=(9.5, 4.8))
    axis.plot(final["blackout_elapsed_s"], final["orientation_heading_deg"], color=COLORS["orientation"], linewidth=0.9, alpha=0.8, label="Course-calibrated exported azimuth")
    axis.plot(final["blackout_elapsed_s"], final["gyro_propagated_heading_deg"], color=COLORS["gyro"], linewidth=1.1, label="Gyro propagated")
    axis.plot(final["blackout_elapsed_s"], final["stabilized_heading_deg"], color=COLORS["phase4"], linewidth=1.5, label="Final stabilized")
    axis.set_title(f"{scenario_id}: runtime-only heading diagnostic", loc="left", weight="bold")
    axis.set_xlabel("Elapsed blackout time (s)")
    axis.set_ylabel("Course (deg clockwise from North)")
    axis.set_ylim(0, 360)
    axis.legend(frameon=False, ncol=3, fontsize=8)
    _style(axis)
    _save(figure, paths["heading"])

    figure, axis = plt.subplots(figsize=(9.5, 4.8))
    axis.plot(raw["blackout_elapsed_s"], raw["estimated_speed_mps"], color=COLORS["raw"], label="V0 raw")
    axis.plot(final["blackout_elapsed_s"], final["estimated_speed_mps"], color=COLORS["phase4"], label="V5 combined")
    axis.plot(final["blackout_elapsed_s"], final["reference_speed_mps"], color=COLORS["reference"], linewidth=1.0, label="VBOX reference - evaluation only")
    axis.set_title(f"{scenario_id}: speed diagnostic", loc="left", weight="bold")
    axis.set_xlabel("Elapsed blackout time (s)")
    axis.set_ylabel("Speed (m/s)")
    axis.legend(frameon=False)
    _style(axis)
    _save(figure, paths["speed"])

    figure, axes = plt.subplots(2, 1, figsize=(9.5, 6.4), sharex=True)
    for axis, raw_field, conditioned_field, label in (
        (axes[0], "raw_forward_acceleration_mps2", "conditioned_forward_acceleration_mps2", "Forward"),
        (axes[1], "raw_left_acceleration_mps2", "conditioned_left_acceleration_mps2", "Left"),
    ):
        axis.plot(final["blackout_elapsed_s"], final[raw_field], color="#888888", linewidth=0.7, alpha=0.7, label="Before")
        axis.plot(final["blackout_elapsed_s"], final[conditioned_field], color=COLORS["phase4"], linewidth=1.1, label="After causal 1 Hz IIR")
        axis.set_ylabel(f"{label} (m/s²)")
        axis.legend(frameon=False, fontsize=8)
        _style(axis)
    axes[0].set_title(f"{scenario_id}: acceleration conditioning", loc="left", weight="bold")
    axes[1].set_xlabel("Elapsed blackout time (s)")
    _save(figure, paths["acceleration"])

    gravity = blackout[[f"gravity_{axis}_mps2" for axis in "xyz"]].to_numpy(dtype=float)
    diagnostic = gravity_euler_diagnostics(
        gravity,
        blackout["orientation_azimuth_deg"],
        blackout["orientation_pitch_deg"],
        blackout["orientation_roll_deg"],
    )
    timeline = blackout["elapsed_s"].to_numpy(dtype=float) - float(blackout["elapsed_s"].iloc[0])
    figure, axis = plt.subplots(figsize=(9.5, 4.8))
    axis.plot(timeline, diagnostic["gravity_tilt_deg"], color=COLORS["phase4"], label="Measured gravity tilt from device +Z")
    axis.plot(timeline, diagnostic["euler_implied_tilt_deg"], color=COLORS["raw"], label="Phase 3 Euler-implied tilt")
    axis.plot(timeline, diagnostic["gravity_euler_disagreement_deg"], color="#7A5195", linewidth=1.0, label="Gravity/Euler disagreement")
    axis.set_title(f"{scenario_id}: orientation sanity check", loc="left", weight="bold")
    axis.set_xlabel("Elapsed blackout time (s)")
    axis.set_ylabel("Angle (degrees)")
    axis.legend(frameon=False, fontsize=8)
    _style(axis)
    _save(figure, paths["orientation"])
    return {name: _relative(path) for name, path in paths.items()}


def _master_plots(ablation: pd.DataFrame, summary: pd.DataFrame, output_dir: Path) -> dict[str, str]:
    standard_ids = summary.loc[summary["standard"], "scenario"].tolist()
    drift_path = output_dir / "plots" / "ablation_drift_bar_chart.png"
    figure, axis = plt.subplots(figsize=(11.5, 6.0))
    variants = [variant for variant in ALL_VARIANTS if variant in set(ablation["variant"])]
    x = np.arange(len(standard_ids), dtype=float)
    width = min(0.36, 0.78 / max(len(variants), 1))
    palette = ["#D55E00", "#CC79A7", "#56B4E9", "#E69F00", "#0072B2", "#009E73"]
    for index, variant in enumerate(variants):
        values = [
            float(ablation.loc[(ablation["scenario"] == scenario) & (ablation["variant"] == variant), "drift_pct"].iloc[0])
            for scenario in standard_ids
        ]
        axis.bar(
            x + (index - (len(variants) - 1) / 2.0) * width,
            values,
            width,
            label=variant.split("_", 1)[0],
            color=palette[ALL_VARIANTS.index(variant)],
        )
    axis.set_xticks(x, [scenario.replace("S1_", "") for scenario in standard_ids], rotation=10)
    axis.set_ylabel("Drift (%)")
    axis.set_title("Phase 4 frozen ablation ladder", loc="left", weight="bold")
    axis.legend(frameon=False, ncol=6, fontsize=8)
    _style(axis)
    _save(figure, drift_path)

    comparison_path = output_dir / "plots" / "raw_vs_phase4_drift_summary.png"
    standard = summary.loc[summary["standard"]]
    x = np.arange(len(standard))
    figure, axis = plt.subplots(figsize=(9.5, 5.4))
    axis.bar(x - 0.18, standard["raw_drift_pct"], 0.36, color=COLORS["raw"], label="V0 raw")
    axis.bar(x + 0.18, standard["phase4_drift_pct"], 0.36, color=COLORS["phase4"], label="V5 combined")
    axis.set_xticks(x, [f"{duration:g} s" for duration in standard["requested_duration_s"]])
    axis.set_ylabel("Drift (%)")
    axis.set_title("Raw vs Phase 4 combined drift", loc="left", weight="bold")
    axis.legend(frameon=False)
    _style(axis)
    _save(figure, comparison_path)
    return {"ablation_drift": _relative(drift_path), "raw_vs_phase4_drift": _relative(comparison_path)}


def _summary_markdown(summary: pd.DataFrame, output_dir: Path, master_plots: dict[str, str]) -> Path:
    standard = summary.loc[summary["standard"]]
    rows = [
        "# Phase 4 Judge Summary",
        "",
        "## Problem",
        "",
        "Phase 3 deliberately integrated nearly raw phone inertial measurements. It was adequate for the 10-second steady case but diverged strongly during turning, stop-go, and long outages.",
        "",
        "## Classical interventions",
        "",
        "Phase 4 replaces physically inconsistent exported Euler tilt with gravity-derived forward/left/up alignment, calibrates exported yaw against distinct pre-blackout phone-GNSS course changes, applies a causal 1 Hz IIR, propagates heading with the runtime-verified gyro channel, gates magnetic/orientation corrections, and applies conservative stationary plus non-holonomic vehicle constraints.",
        "",
        "## Before and after",
        "",
        "| Scenario | Raw drift | Phase 4 drift | Raw final error | Phase 4 final error | Improvement |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in standard.itertuples(index=False):
        rows.append(
            f"| {row.scenario} | {row.raw_drift_pct:.3f}% | {row.phase4_drift_pct:.3f}% | {row.raw_final_error_m:.3f} m | {row.phase4_final_error_m:.3f} m | {row.final_error_improvement_pct:.3f}% |"
        )
    rows.extend(
        [
            "",
            "## Leakage boundary",
            "",
            "The estimator and calibrator receive only `RuntimeDataset` sensor history, strictly pre-blackout phone GNSS, and GNSS-free blackout rows. VBOX enters only after every trajectory is complete, through the separate evaluation function. No VBOX metric selected any parameter.",
            "",
            "## Scope",
            "",
            "This is a lightweight classical baseline. It contains no EKF, UKF, machine learning, map matching, road graph, or Android application.",
            "",
            "## Key plots",
            "",
            f"- Ablation drift: `{master_plots['ablation_drift']}`",
            f"- Raw vs Phase 4: `{master_plots['raw_vs_phase4_drift']}`",
            "- Per-scenario trajectory, error, heading, speed, conditioning, and orientation plots: `results/phase4/io_vnbd/s1/plots/`",
            "",
            "The 10-second steady regression and every negative ablation are retained in the machine-readable tables.",
        ]
    )
    path = output_dir / "PHASE4_JUDGE_SUMMARY.md"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", default="S1")
    parser.add_argument("--config", type=Path, default=Path("configs/phase4/io_vnbd_s1_classical.json"))
    parser.add_argument("--scenario", help="Run one configured benchmark scenario ID.")
    parser.add_argument("--start", type=float, help="Custom blackout start in elapsed seconds.")
    parser.add_argument("--duration", type=float, help="Custom blackout duration in seconds.")
    parser.add_argument("--scenario-id", help="ID for a custom blackout.")
    parser.add_argument("--ablation", choices=("all", "final"), default="all")
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.scenario and (args.start is not None or args.duration is not None):
        raise SystemExit("--scenario cannot be combined with --start/--duration.")
    if (args.start is None) != (args.duration is None):
        raise SystemExit("Custom execution requires both --start and --duration.")
    config_path = (args.config if args.config.is_absolute() else ROOT / args.config).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    settings = Phase4Settings.from_dict(config)
    benchmark_path = (ROOT / config["benchmark_config"]).resolve()
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    scenarios = [scenario for scenario in benchmark["scenarios"] if scenario.get("standard")]
    scenarios.append(config["custom_judge_scenario"])
    if args.start is not None:
        scenarios = [{
            "id": args.scenario_id or f"{args.session}_{float(args.duration):g}_PHASE4_CUSTOM",
            "start_s": float(args.start),
            "duration_s": float(args.duration),
            "type": "custom_phase4",
            "standard": False,
        }]
    elif args.scenario:
        scenarios = [scenario for scenario in scenarios if scenario["id"].upper() == args.scenario.upper()]
        if not scenarios:
            raise SystemExit(f"Scenario not found: {args.scenario}")

    journey = load_journey(args.session, project_root_path=ROOT)
    if journey.session_id.upper() != str(config["session"]).upper():
        raise SystemExit("Configuration session does not match loaded journey.")
    output_dir = (args.output_dir or ROOT / "results" / "phase4" / "io_vnbd" / journey.session_id.lower()).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    source_before = {
        "smartphone_sha256": sha256_file(journey.smartphone_path),
        "vehicle_reference_sha256": sha256_file(journey.vehicle_path),
    }
    variants = ALL_VARIANTS if args.ablation == "all" else (V0, "V5_PHASE4_COMBINED")
    all_results: list[dict[str, Any]] = []
    ablation_rows: list[dict[str, Any]] = []
    diagnostic_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    total_estimator_samples = 0
    total_estimator_seconds = 0.0

    for scenario in scenarios:
        scenario_id = str(scenario["id"])
        window = BlackoutWindow(float(scenario["start_s"]), float(scenario["duration_s"]))
        experiment = create_blackout_experiment(journey, window)
        sensor_history = experiment.runtime.sensor_data.loc[
            experiment.runtime.sensor_data["elapsed_s"] < window.start_s
        ].copy()
        gnss_history = experiment.runtime.gnss_observations.loc[
            experiment.runtime.gnss_observations["elapsed_s"] < window.start_s
        ].copy()
        blackout = extract_blackout_sensor_data(experiment.runtime, window)
        raw_initialization = build_phone_initialization(sensor_history, gnss_history, window.start_s)
        raw_start = time.perf_counter()
        raw_prediction = integrate_raw_dead_reckoning(blackout, raw_initialization)
        raw_seconds = time.perf_counter() - raw_start
        # Reference crosses the boundary only after raw prediction is complete.
        raw_evaluation = evaluate_raw_dr_prediction(raw_prediction, experiment.reference)
        calibration = build_phase4_calibration(sensor_history, gnss_history, window.start_s, settings)
        variant_results: dict[str, dict[str, Any]] = {
            V0: {"metrics": raw_evaluation.metrics, "processing_seconds": raw_seconds}
        }
        timeseries: dict[str, pd.DataFrame] = {V0: raw_evaluation.timeseries}
        predictions: dict[str, Any] = {}
        for variant in variants:
            if variant == V0:
                continue
            started = time.perf_counter()
            prediction = integrate_calibrated_dead_reckoning(blackout, calibration, settings, variant)
            processing_seconds = time.perf_counter() - started
            # VBOX remains evaluation-only and is introduced here, after prediction.
            evaluation = evaluate_raw_dr_prediction(as_raw_prediction(prediction), experiment.reference)
            variant_results[variant] = {
                "metrics": evaluation.metrics,
                "improvement_vs_raw": _improvement(raw_evaluation.metrics, evaluation.metrics),
                "processing_seconds": processing_seconds,
                "throughput_samples_per_second": len(blackout) / max(processing_seconds, 1e-12),
            }
            timeseries[variant] = evaluation.timeseries
            predictions[variant] = prediction
            total_estimator_samples += len(blackout)
            total_estimator_seconds += processing_seconds
        final_variant = "V5_PHASE4_COMBINED"
        final_prediction = predictions[final_variant]
        final_evaluation = timeseries[final_variant]
        diagnostics = phase4_sensor_diagnostics(blackout, calibration, final_prediction)
        diagnostics_row = {"scenario": scenario_id, **diagnostics}
        diagnostics_row["gyro_axis_course_correlations"] = json.dumps(diagnostics_row["gyro_axis_course_correlations"], sort_keys=True)
        diagnostics_row["gyro_axis_course_scales"] = json.dumps(diagnostics_row["gyro_axis_course_scales"], sort_keys=True)
        diagnostic_rows.append(diagnostics_row)

        scenario_dir = output_dir / "scenarios" / scenario_id.lower()
        scenario_dir.mkdir(parents=True, exist_ok=True)
        artifact_variants: dict[str, dict[str, str]] = {}
        for variant, evaluation_frame in timeseries.items():
            prediction_path = scenario_dir / f"{variant.lower()}_prediction.csv"
            timeseries_path = scenario_dir / f"{variant.lower()}_timeseries.csv"
            prediction_frame = raw_prediction.data if variant == V0 else predictions[variant].data
            prediction_frame.to_csv(prediction_path, index=False)
            evaluation_frame.to_csv(timeseries_path, index=False)
            artifact_variants[variant] = {
                "prediction_csv": _relative(prediction_path),
                "timeseries_csv": _relative(timeseries_path),
            }
        plots = _plot_scenario(scenario_id, raw_evaluation.timeseries, final_evaluation, blackout, output_dir)
        for variant, result in variant_results.items():
            metrics = result["metrics"]
            improvement = result.get("improvement_vs_raw", {"final_error_improvement_pct": 0.0, "rmse_improvement_pct": 0.0, "drift_improvement_pct": 0.0})
            ablation_rows.append({
                "scenario": scenario_id,
                "standard": bool(scenario.get("standard", False)),
                "requested_start_s": window.start_s,
                "requested_duration_s": window.duration_s,
                "actual_duration_s": experiment.metadata.actual_masked_duration_s,
                "variant": variant,
                "final_relative_error_m": metrics["final_position_error_m"],
                "drift_pct": metrics["drift_percentage"],
                "rmse_m": metrics["rmse_position_error_m"],
                **improvement,
            })
        raw_metrics = raw_evaluation.metrics
        final_metrics = variant_results[final_variant]["metrics"]
        final_improvement = variant_results[final_variant]["improvement_vs_raw"]
        summary_rows.append({
            "scenario": scenario_id,
            "scenario_type": scenario.get("type", "custom"),
            "standard": bool(scenario.get("standard", False)),
            "requested_start_s": window.start_s,
            "requested_duration_s": window.duration_s,
            "actual_duration_s": experiment.metadata.actual_masked_duration_s,
            "sample_count": experiment.metadata.masked_sample_count,
            "reference_distance_m": final_metrics["reference_distance_m"],
            "raw_final_error_m": raw_metrics["final_position_error_m"],
            "phase4_final_error_m": final_metrics["final_position_error_m"],
            "raw_drift_pct": raw_metrics["drift_percentage"],
            "phase4_drift_pct": final_metrics["drift_percentage"],
            "raw_rmse_m": raw_metrics["rmse_position_error_m"],
            "phase4_rmse_m": final_metrics["rmse_position_error_m"],
            **final_improvement,
        })
        scenario_result = {
            "scenario": scenario,
            "blackout_metadata": experiment.metadata.to_dict(),
            "calibration": calibration.to_dict(),
            "diagnostics": diagnostics,
            "ablations": variant_results,
            "artifacts": {"variants": artifact_variants, "plots": plots},
        }
        result_path = scenario_dir / "result.json"
        result_path.write_text(json.dumps(scenario_result, indent=2), encoding="utf-8")
        scenario_result["artifacts"]["result_json"] = _relative(result_path)
        all_results.append(scenario_result)
        print(
            f"{scenario_id}: raw {raw_metrics['drift_percentage']:.3f}% -> "
            f"Phase 4 {final_metrics['drift_percentage']:.3f}% "
            f"({final_improvement['drift_improvement_pct']:+.3f}%)"
        )

    summary = pd.DataFrame(summary_rows)
    ablation = pd.DataFrame(ablation_rows)
    diagnostics = pd.DataFrame(diagnostic_rows)
    summary.to_csv(output_dir / "summary.csv", index=False)
    ablation.to_csv(output_dir / "ablation.csv", index=False)
    diagnostics.to_csv(output_dir / "diagnostics.csv", index=False)
    (output_dir / "summary.json").write_text(json.dumps({"phase": 4, "algorithm": PHASE4_ALGORITHM, "results": all_results}, indent=2), encoding="utf-8")
    (output_dir / "ablation.json").write_text(json.dumps(ablation_rows, indent=2), encoding="utf-8")
    master_plots = _master_plots(ablation, summary, output_dir)
    judge_summary = _summary_markdown(summary, output_dir, master_plots)
    source_after = {
        "smartphone_sha256": sha256_file(journey.smartphone_path),
        "vehicle_reference_sha256": sha256_file(journey.vehicle_path),
    }
    if source_before != source_after:
        raise AssertionError("Original dataset checksums changed during Phase 4 execution.")
    manifest = {
        "phase": 4,
        "parent_git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "algorithm_version": PHASE4_ALGORITHM,
        "phase4_config": _relative(config_path),
        "blackout_config": _relative(benchmark_path),
        "dataset": "IO-VNBD",
        "session": journey.session_id,
        "execution_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "sensor_fields": list(blackout.columns),
        "calibration": config["calibration"],
        "filtering": config["filtering"],
        "motion_state": config["motion_state"],
        "heading": config["heading"],
        "magnetometer": config["magnetometer"],
        "coordinate_frame": config["coordinate_convention"],
        "real_time_complexity": "O(n) time and O(window_samples) stationary-detector memory; all final processing is causal",
        "measured_estimator_samples": total_estimator_samples,
        "measured_estimator_seconds": total_estimator_seconds,
        "measured_throughput_samples_per_second": total_estimator_samples / max(total_estimator_seconds, 1e-12),
        "reference_isolation": "VBOX EvaluationReference is passed only to evaluate_raw_dr_prediction after each prediction completes",
        "source_integrity": {"before": source_before, "after": source_after, "unchanged": True},
        "scenario_ids": [row["scenario"] for row in summary_rows],
        "artifacts": {
            "summary_csv": _relative(output_dir / "summary.csv"),
            "summary_json": _relative(output_dir / "summary.json"),
            "ablation_csv": _relative(output_dir / "ablation.csv"),
            "ablation_json": _relative(output_dir / "ablation.json"),
            "diagnostics_csv": _relative(output_dir / "diagnostics.csv"),
            "judge_summary": _relative(judge_summary),
            "master_plots": master_plots,
        },
    }
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote Phase 4 outputs to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
