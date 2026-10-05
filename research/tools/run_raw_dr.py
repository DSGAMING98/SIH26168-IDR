#!/usr/bin/env python3
"""Run the Phase 3 raw inertial dead-reckoning benchmark."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
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

from idr.blackout import BlackoutWindow, create_blackout_experiment  # noqa: E402
from idr.dead_reckoning import (  # noqa: E402
    RAW_DR_ALGORITHM,
    build_phone_initialization,
    extract_blackout_sensor_data,
    integrate_raw_dead_reckoning,
)
from idr.io_vnbd import load_journey, sha256_file  # noqa: E402
from idr.raw_dr_evaluation import evaluate_raw_dr_prediction  # noqa: E402


COLORS = {
    "prediction": "#D55E00",
    "reference": "#0072B2",
    "error": "#7A5195",
    "acceleration": "#009E73",
    "grid": "#D9DEE5",
}


def _style(axis: Any) -> None:
    axis.grid(True, color=COLORS["grid"], linewidth=0.6, alpha=0.8)
    axis.spines[["top", "right"]].set_visible(False)


def _save(figure: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def _plot_trajectory(timeseries: pd.DataFrame, scenario_id: str, output: Path) -> None:
    figure, axis = plt.subplots(figsize=(8.2, 7.0))
    axis.plot(
        timeseries["reference_relative_x_m"],
        timeseries["reference_relative_y_m"],
        color=COLORS["reference"],
        linewidth=2.0,
        label="VBOX reference - evaluation only",
    )
    axis.plot(
        timeseries["predicted_relative_x_m"],
        timeseries["predicted_relative_y_m"],
        color=COLORS["prediction"],
        linewidth=1.6,
        label="Raw inertial DR",
    )
    axis.scatter(0.0, 0.0, color="#009E73", s=55, label="Blackout start", zorder=5)
    axis.scatter(
        timeseries["reference_relative_x_m"].iloc[-1],
        timeseries["reference_relative_y_m"].iloc[-1],
        color=COLORS["reference"],
        marker="X",
        s=70,
        label="Reference end",
        zorder=5,
    )
    axis.scatter(
        timeseries["predicted_relative_x_m"].iloc[-1],
        timeseries["predicted_relative_y_m"].iloc[-1],
        color=COLORS["prediction"],
        marker="X",
        s=70,
        label="Raw DR end",
        zorder=5,
    )
    axis.set_title(f"{scenario_id}: blackout-relative trajectory", loc="left", weight="bold")
    axis.set_xlabel("East displacement (m)")
    axis.set_ylabel("North displacement (m)")
    axis.set_aspect("equal", adjustable="datalim")
    axis.legend(frameon=False, fontsize=8)
    _style(axis)
    _save(figure, output)


def _plot_error(timeseries: pd.DataFrame, scenario_id: str, output: Path) -> None:
    figure, axis = plt.subplots(figsize=(9.5, 4.8))
    axis.plot(
        timeseries["blackout_elapsed_s"],
        timeseries["relative_position_error_m"],
        color=COLORS["error"],
        linewidth=1.5,
    )
    axis.set_title(f"{scenario_id}: raw DR relative error growth", loc="left", weight="bold")
    axis.set_xlabel("Elapsed blackout time (s)")
    axis.set_ylabel("Relative position error (m)")
    _style(axis)
    _save(figure, output)


def _plot_speed(timeseries: pd.DataFrame, scenario_id: str, output: Path) -> None:
    figure, axis = plt.subplots(figsize=(9.5, 4.8))
    axis.plot(
        timeseries["blackout_elapsed_s"],
        timeseries["estimated_speed_mps"],
        color=COLORS["prediction"],
        linewidth=1.3,
        label="Raw DR predicted speed",
    )
    axis.plot(
        timeseries["blackout_elapsed_s"],
        timeseries["reference_speed_mps"],
        color=COLORS["reference"],
        linewidth=1.1,
        label="VBOX reference - evaluation only",
    )
    axis.set_title(f"{scenario_id}: speed diagnostic", loc="left", weight="bold")
    axis.set_xlabel("Elapsed blackout time (s)")
    axis.set_ylabel("Speed (m/s)")
    axis.legend(frameon=False)
    _style(axis)
    _save(figure, output)


def _plot_acceleration(timeseries: pd.DataFrame, scenario_id: str, output: Path) -> None:
    horizontal_magnitude = np.hypot(
        timeseries["local_acceleration_x_mps2"],
        timeseries["local_acceleration_y_mps2"],
    )
    figure, axis = plt.subplots(figsize=(9.5, 4.8))
    axis.plot(timeseries["blackout_elapsed_s"], timeseries["local_acceleration_x_mps2"], linewidth=0.8, label="East")
    axis.plot(timeseries["blackout_elapsed_s"], timeseries["local_acceleration_y_mps2"], linewidth=0.8, label="North")
    axis.plot(
        timeseries["blackout_elapsed_s"],
        horizontal_magnitude,
        color=COLORS["acceleration"],
        linewidth=1.0,
        alpha=0.8,
        label="Horizontal magnitude",
    )
    axis.set_title(f"{scenario_id}: unfiltered transformed acceleration", loc="left", weight="bold")
    axis.set_xlabel("Elapsed blackout time (s)")
    axis.set_ylabel("Acceleration (m/s²)")
    axis.legend(frameon=False, ncol=3)
    _style(axis)
    _save(figure, output)


def _run_scenario(journey: Any, scenario: dict[str, Any], output_dir: Path) -> tuple[dict[str, Any], pd.DataFrame]:
    window = BlackoutWindow(float(scenario["start_s"]), float(scenario["duration_s"]))
    experiment = create_blackout_experiment(journey, window)
    sensor_history = experiment.runtime.sensor_data[
        experiment.runtime.sensor_data["elapsed_s"] < window.start_s
    ].copy()
    gnss_history = experiment.runtime.gnss_observations[
        experiment.runtime.gnss_observations["elapsed_s"] < window.start_s
    ].copy()
    initialization = build_phone_initialization(sensor_history, gnss_history, window.start_s)
    blackout_runtime = extract_blackout_sensor_data(experiment.runtime, window)

    # The estimator receives only GNSS-free blackout rows and the already-built
    # legitimate phone initialization state. Reference data enters only below.
    prediction = integrate_raw_dead_reckoning(blackout_runtime, initialization)
    evaluation = evaluate_raw_dr_prediction(prediction, experiment.reference)

    scenario_id = str(scenario["id"])
    scenario_slug = scenario_id.lower()
    scenario_dir = output_dir / "scenarios"
    scenario_dir.mkdir(parents=True, exist_ok=True)
    prediction_path = scenario_dir / f"{scenario_slug}_prediction.csv"
    timeseries_path = scenario_dir / f"{scenario_slug}_timeseries.csv"
    metrics_path = scenario_dir / f"{scenario_slug}_metrics.json"
    prediction.data.to_csv(prediction_path, index=False)
    evaluation.timeseries.to_csv(timeseries_path, index=False)

    plot_paths = {
        "trajectory": output_dir / "plots" / f"{scenario_slug}_trajectory.png",
        "error": output_dir / "plots" / f"{scenario_slug}_error.png",
        "speed": output_dir / "plots" / f"{scenario_slug}_speed.png",
        "acceleration": output_dir / "plots" / f"{scenario_slug}_acceleration.png",
    }
    _plot_trajectory(evaluation.timeseries, scenario_id, plot_paths["trajectory"])
    _plot_error(evaluation.timeseries, scenario_id, plot_paths["error"])
    _plot_speed(evaluation.timeseries, scenario_id, plot_paths["speed"])
    _plot_acceleration(evaluation.timeseries, scenario_id, plot_paths["acceleration"])

    result = {
        "scenario_id": scenario_id,
        "scenario_type": scenario.get("type", "custom"),
        "standard": bool(scenario.get("standard", False)),
        "requested_start_s": window.start_s,
        "requested_duration_s": window.duration_s,
        "actual_duration_s": experiment.metadata.actual_masked_duration_s,
        "sample_count": experiment.metadata.masked_sample_count,
        "actual_first_masked_sample_s": experiment.metadata.actual_first_masked_sample_s,
        "actual_last_masked_sample_s": experiment.metadata.actual_last_masked_sample_s,
        "initialization": initialization.to_dict(),
        "performance": evaluation.metrics,
        "artifacts": {
            "prediction_csv": str(prediction_path.relative_to(ROOT)).replace("\\", "/"),
            "timeseries_csv": str(timeseries_path.relative_to(ROOT)).replace("\\", "/"),
            "metrics_json": str(metrics_path.relative_to(ROOT)).replace("\\", "/"),
            "plots": {
                name: str(path.relative_to(ROOT)).replace("\\", "/")
                for name, path in plot_paths.items()
            },
        },
    }
    metrics_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result, evaluation.timeseries


def _summary_row(result: dict[str, Any]) -> dict[str, Any]:
    initialization = result["initialization"]
    performance = result["performance"]
    return {
        "scenario": result["scenario_id"],
        "standard": result["standard"],
        "duration_s": result["actual_duration_s"],
        "sample_count": result["sample_count"],
        "distance_m": performance["reference_distance_m"],
        "final_error_m": performance["final_position_error_m"],
        "drift_pct": performance["drift_percentage"],
        "mean_error_m": performance["mean_position_error_m"],
        "rmse_m": performance["rmse_position_error_m"],
        "max_error_m": performance["maximum_position_error_m"],
        "p95_error_m": performance["p95_position_error_m"],
        "initial_speed_mps": initialization["initial_speed_mps"],
        "initial_heading_deg": initialization["initial_heading_deg"],
        "heading_source": initialization["heading_source"],
        "gnss_observation_age_s": initialization["gnss_observation_age_s"],
        "gnss_solution_change_age_s": initialization["gnss_solution_change_age_s"],
        "initial_phone_gnss_vbox_offset_m": performance["absolute_initial_phone_gnss_vbox_offset_m"],
        "absolute_final_error_m": performance["absolute_final_position_error_m"],
        "final_predicted_speed_mps": performance["final_predicted_speed_mps"],
        "max_predicted_speed_mps": performance["maximum_predicted_speed_mps"],
        "unrealistic_speed_fraction": performance["unrealistic_speed_fraction"],
        "mean_horizontal_acceleration_mps2": performance["mean_horizontal_acceleration_mps2"],
        "max_horizontal_acceleration_mps2": performance["maximum_horizontal_acceleration_mps2"],
    }


def _master_plots(
    results: list[dict[str, Any]],
    timeseries: dict[str, pd.DataFrame],
    output_dir: Path,
) -> dict[str, str]:
    standard = sorted(
        [result for result in results if result["standard"]],
        key=lambda result: result["requested_duration_s"],
    )
    if not standard:
        return {}
    labels = [f"{result['requested_duration_s']:g} s" for result in standard]
    drift = [result["performance"]["drift_percentage"] for result in standard]
    final_error = [result["performance"]["final_position_error_m"] for result in standard]

    drift_path = output_dir / "plots" / "raw_dr_drift_summary.png"
    figure, axis = plt.subplots(figsize=(8.5, 5.2))
    bars = axis.bar(labels, drift, color="#D55E00")
    axis.bar_label(bars, fmt="%.1f%%", padding=3)
    axis.set_title("Raw inertial DR drift by standard blackout", loc="left", weight="bold")
    axis.set_xlabel("Requested blackout duration")
    axis.set_ylabel("Relative final error / reference distance (%)")
    _style(axis)
    _save(figure, drift_path)

    final_path = output_dir / "plots" / "raw_dr_final_error_summary.png"
    figure, axis = plt.subplots(figsize=(8.5, 5.2))
    bars = axis.bar(labels, final_error, color="#7A5195")
    axis.bar_label(bars, fmt="%.1f m", padding=3)
    axis.set_title("Raw inertial DR final relative error", loc="left", weight="bold")
    axis.set_xlabel("Requested blackout duration")
    axis.set_ylabel("Final relative position error (m)")
    _style(axis)
    _save(figure, final_path)

    growth_path = output_dir / "plots" / "raw_dr_error_growth_comparison.png"
    figure, axis = plt.subplots(figsize=(9.5, 5.5))
    for result in standard:
        frame = timeseries[result["scenario_id"]]
        axis.plot(
            frame["blackout_elapsed_s"],
            frame["relative_position_error_m"],
            linewidth=1.4,
            label=result["scenario_id"],
        )
    axis.set_title("Raw inertial DR error growth comparison", loc="left", weight="bold")
    axis.set_xlabel("Elapsed blackout time (s)")
    axis.set_ylabel("Relative position error (m)")
    axis.legend(frameon=False, fontsize=8)
    _style(axis)
    _save(figure, growth_path)
    return {
        "drift_summary": str(drift_path.relative_to(ROOT)).replace("\\", "/"),
        "final_error_summary": str(final_path.relative_to(ROOT)).replace("\\", "/"),
        "error_growth_comparison": str(growth_path.relative_to(ROOT)).replace("\\", "/"),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", default="S1")
    parser.add_argument("--config", type=Path, default=Path("configs/blackouts/io_vnbd_s1.json"))
    parser.add_argument("--scenario", help="Run one configured scenario ID.")
    parser.add_argument("--start", type=float, help="Custom blackout start in elapsed seconds.")
    parser.add_argument("--duration", type=float, help="Custom positive blackout duration in seconds.")
    parser.add_argument("--scenario-id", help="ID for a custom blackout.")
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.scenario and (args.start is not None or args.duration is not None):
        raise SystemExit("--scenario cannot be combined with --start/--duration.")
    if (args.start is None) != (args.duration is None):
        raise SystemExit("Custom execution requires both --start and --duration.")
    config_path = args.config if args.config.is_absolute() else ROOT / args.config
    config = json.loads(config_path.read_text(encoding="utf-8"))
    journey = load_journey(args.session, project_root_path=ROOT)
    if str(config["session"]).upper() != journey.session_id:
        raise SystemExit("Configuration session does not match --session.")
    if args.start is not None:
        duration_label = f"{float(args.duration):g}".replace(".", "p")
        scenarios = [{
            "id": args.scenario_id or f"{journey.session_id}_{duration_label}_RAW_DR_CUSTOM",
            "start_s": float(args.start),
            "duration_s": float(args.duration),
            "type": "custom_raw_dr",
            "standard": False,
        }]
    elif args.scenario:
        scenarios = [
            scenario for scenario in config["scenarios"]
            if scenario["id"].upper() == args.scenario.upper()
        ]
        if not scenarios:
            raise SystemExit(f"Scenario not found in configuration: {args.scenario}")
    else:
        scenarios = list(config["scenarios"])

    output_dir = (
        args.output_dir
        or ROOT / "results" / "raw_dr" / "io_vnbd" / journey.session_id.lower()
    ).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    source_hashes_before = {
        "smartphone_sha256": sha256_file(journey.smartphone_path),
        "vehicle_reference_sha256": sha256_file(journey.vehicle_path),
    }
    results: list[dict[str, Any]] = []
    timeseries: dict[str, pd.DataFrame] = {}
    for scenario in scenarios:
        result, frame = _run_scenario(journey, scenario, output_dir)
        results.append(result)
        timeseries[result["scenario_id"]] = frame
        print(
            f"{result['scenario_id']}: "
            f"{result['performance']['final_position_error_m']:.3f} m final relative error, "
            f"{result['performance']['drift_percentage']:.3f}% drift"
        )
    summary_rows = [_summary_row(result) for result in results]
    pd.DataFrame(summary_rows).to_csv(output_dir / "summary.csv", index=False)
    (output_dir / "summary.json").write_text(
        json.dumps({"phase": 3, "algorithm": RAW_DR_ALGORITHM, "results": results}, indent=2),
        encoding="utf-8",
    )
    master_plots = _master_plots(results, timeseries, output_dir)
    source_hashes_after = {
        "smartphone_sha256": sha256_file(journey.smartphone_path),
        "vehicle_reference_sha256": sha256_file(journey.vehicle_path),
    }
    if source_hashes_before != source_hashes_after:
        raise AssertionError("Original dataset file checksums changed during raw DR execution.")
    manifest = {
        "phase": 3,
        "git_parent_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "interpreter_path": sys.executable,
        "python_version": sys.version,
        "dataset": "IO-VNBD",
        "session": journey.session_id,
        "benchmark_config_path": str(config_path.relative_to(ROOT)).replace("\\", "/"),
        "execution_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "algorithm": RAW_DR_ALGORITHM,
        "gravity_removal": "device linear acceleration = accelerometer - Android gravity",
        "orientation_transform": "Rz(-azimuth) @ Rx(-pitch) @ Ry(roll), device to local ENU",
        "integration_method": "trapezoidal acceleration and velocity integration using measured dt",
        "coordinate_convention": "local ENU: x East, y North, z Up; phone GNSS origin; no EPSG assertion",
        "estimator_inputs": "GNSS-free blackout RuntimeDataset.sensor_data rows plus pre-blackout phone initialization",
        "source_integrity": {
            "before": source_hashes_before,
            "after": source_hashes_after,
            "unchanged": True,
        },
        "scenario_ids": [result["scenario_id"] for result in results],
        "result_artifacts": {
            "summary_csv": str((output_dir / "summary.csv").relative_to(ROOT)).replace("\\", "/"),
            "summary_json": str((output_dir / "summary.json").relative_to(ROOT)).replace("\\", "/"),
            "master_plots": master_plots,
            "scenario_artifacts": [result["artifacts"] for result in results],
        },
    }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"Wrote Phase 3 outputs to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
