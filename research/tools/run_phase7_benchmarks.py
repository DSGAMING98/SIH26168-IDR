#!/usr/bin/env python3
"""Run the frozen Phase 7 GNSS loss/reacquisition benchmarks."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import platform
import subprocess
import sys
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

from idr.blackout import BlackoutWindow, create_blackout_experiment  # noqa: E402
from idr.calibrated_dr import Phase4Settings  # noqa: E402
from idr.hybrid.hybrid_idr import HybridSettings  # noqa: E402
from idr.io_vnbd import load_journey, sha256_file  # noqa: E402
from idr.map_matching import MapMatcherConfig, RoadGraph  # noqa: E402
from idr.ml.velocity_model import load_velocity_bundle  # noqa: E402
from idr.phase7 import (  # noqa: E402
    Phase7Config,
    evaluate_phase7_runtime,
    run_phase7_runtime,
)


COLORS = {
    "reference": "#202124",
    "idr": "#0072B2",
    "hard": "#D55E00",
    "p7": "#009E73",
    "blackout": "#F4B183",
}


def load_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    if not source.is_absolute():
        source = ROOT / source
    return json.loads(source.read_text(encoding="utf-8"))


def file_hash(path: Path | str) -> str:
    source = Path(path)
    if not source.is_absolute():
        source = ROOT / source
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalized(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized(payload), indent=2, allow_nan=False) + "\n", encoding="utf-8")


def scenarios() -> list[dict[str, Any]]:
    blackout = load_json("configs/blackouts/io_vnbd_s1.json")
    phase4 = load_json("configs/phase4/io_vnbd_s1_classical.json")
    split = load_json("configs/phase5/io_vnbd_s1_split.json")
    result = [dict(item) for item in blackout["scenarios"] if item.get("standard")]
    result.append(dict(phase4["custom_judge_scenario"]))
    surprise = next(item for item in split["quarantine_intervals"] if item["id"] == "S1_PHASE5_SURPRISE")
    result.append({
        "id": "S1_PHASE5_SURPRISE",
        "start_s": surprise["blackout_start_s"],
        "duration_s": surprise["duration_s"],
        "type": "preselected_surprise_holdout",
        "standard": False,
    })
    return result


def style(axis: Any) -> None:
    axis.grid(True, alpha=0.22)
    axis.spines[["top", "right"]].set_visible(False)


def save_figure(figure: Any, path: Path) -> None:
    figure.tight_layout()
    figure.savefig(path, dpi=170, bbox_inches="tight")
    plt.close(figure)


def representative_plots(evaluation: Any, window: BlackoutWindow, output: Path) -> None:
    frame = evaluation.timeseries
    elapsed = frame["elapsed_s"].to_numpy(dtype=float) - window.end_s
    recovery_start = evaluation.metrics["recovery_start_s"]
    recovery_x = None if recovery_start is None else recovery_start - window.end_s

    figure, axis = plt.subplots(figsize=(8, 6))
    from idr.evaluation import geodetic_to_local_xy_m
    reference = geodetic_to_local_xy_m(
        frame["reference_latitude_deg"], frame["reference_longitude_deg"],
        float(frame["reference_latitude_deg"].iloc[0]),
        float(frame["reference_longitude_deg"].iloc[0]),
    )
    axis.plot(reference.x_east_m, reference.y_north_m, color=COLORS["reference"], lw=2, label="VBOX evaluation reference")
    axis.plot(frame["idr_east_m"] - frame["idr_east_m"].iloc[0], frame["idr_north_m"] - frame["idr_north_m"].iloc[0], color=COLORS["idr"], lw=1.4, label="Phase 6 IDR (local displacement)")
    axis.plot(frame["b1_east_m"] - frame["b1_east_m"].iloc[0], frame["b1_north_m"] - frame["b1_north_m"].iloc[0], color=COLORS["hard"], lw=1.2, label="B1 hard snap")
    axis.plot(frame["navigation_east_m"] - frame["navigation_east_m"].iloc[0], frame["navigation_north_m"] - frame["navigation_north_m"].iloc[0], color=COLORS["p7"], lw=2, label="P7 smooth navigation")
    axis.set(title="S1_60_STOP_GO: GNSS loss and smooth recovery", xlabel="East (m)", ylabel="North (m)")
    axis.set_aspect("equal", adjustable="datalim")
    axis.legend(fontsize=8)
    style(axis)
    save_figure(figure, output / "trajectory_recovery.png")

    figure, axis = plt.subplots(figsize=(9, 4.5))
    axis.plot(elapsed, frame["b0_absolute_error_m"], color="#9C755F", lw=1, label="B0 first returned coordinate")
    axis.plot(elapsed, frame["b1_absolute_error_m"], color=COLORS["hard"], lw=1.3, label="B1 first fresh fix")
    axis.plot(elapsed, frame["p7_absolute_error_m"], color=COLORS["p7"], lw=2, label="P7 smooth recovery")
    axis.axvspan(-window.duration_s, 0, color=COLORS["blackout"], alpha=0.25, label="GNSS blackout")
    axis.axvline(0, color="#555555", ls="--", lw=1)
    axis.set(title="Absolute evaluation error around reacquisition", xlabel="Time from blackout end (s)", ylabel="Horizontal error (m)")
    axis.legend(fontsize=8, ncol=2)
    style(axis)
    save_figure(figure, output / "position_error_vs_time.png")

    states = ["GNSS_ACTIVE", "GNSS_DEGRADED", "IDR_ACTIVE", "GNSS_VERIFYING", "GNSS_RECOVERING"]
    mapping = {name: index for index, name in enumerate(states)}
    figure, axis = plt.subplots(figsize=(10, 3.8))
    axis.step(elapsed, [mapping[item] for item in frame["navigation_state"]], where="post", color=COLORS["p7"], lw=1.8)
    axis.axvline(0, color="#555555", ls="--", lw=1, label="Blackout end")
    if recovery_x is not None:
        axis.axvline(recovery_x, color="#6F4E7C", ls=":", lw=1.3, label="GNSS verified")
    axis.set_yticks(range(len(states)), states)
    axis.set(title="Deterministic navigation state timeline", xlabel="Time from blackout end (s)")
    axis.legend(fontsize=8)
    style(axis)
    save_figure(figure, output / "navigation_state_timeline.png")

    figure, axis = plt.subplots(figsize=(8, 4.4))
    hard = evaluation.metrics["b1_first_fresh_fix_hard_snap_jump_m"] or 0.0
    smooth = evaluation.metrics["phase7_maximum_instantaneous_correction_m"]
    axis.bar(["B1 hard snap", "P7 largest step"], [hard, smooth], color=[COLORS["hard"], COLORS["p7"]])
    for index, value in enumerate((hard, smooth)):
        axis.text(index, value, f"{value:.2f} m", ha="center", va="bottom")
    axis.set(title="Reacquisition discontinuity", ylabel="Instantaneous position correction (m)")
    style(axis)
    save_figure(figure, output / "jump_comparison.png")

    classes = ["NO_GNSS", "INVALID", "REPEATED", "FRESH"]
    class_map = {name: index for index, name in enumerate(classes)}
    figure, axes = plt.subplots(2, 1, figsize=(10, 5.8), sharex=True)
    axes[0].scatter(elapsed, [class_map.get(item, np.nan) for item in frame["gnss_classification"]], s=6, color=COLORS["idr"])
    axes[0].set_yticks(range(len(classes)), classes)
    axes[0].set_ylabel("Classification")
    ages = frame["seconds_since_last_fresh_fix"].replace([np.inf, -np.inf], np.nan)
    axes[1].plot(elapsed, ages, color="#6F4E7C", lw=1.2)
    axes[1].set(xlabel="Time from blackout end (s)", ylabel="Fresh-fix age (s)")
    for axis in axes:
        axis.axvline(0, color="#555555", ls="--", lw=1)
        style(axis)
    figure.suptitle("Rows at 10 Hz are not fresh GNSS fixes at 10 Hz")
    save_figure(figure, output / "gnss_freshness_timeline.png")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", help="Run one frozen scenario ID")
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    phase7_path = ROOT / "configs/phase7/io_vnbd_s1_phase7.json"
    phase7 = load_json(phase7_path)
    if phase7.get("status") != "frozen_before_held_out_evaluation":
        raise SystemExit("Phase 7 configuration is not frozen; held-out evaluation refused.")
    selected = scenarios()
    if args.scenario:
        selected = [item for item in selected if item["id"].upper() == args.scenario.upper()]
        if not selected:
            raise SystemExit(f"Unknown scenario: {args.scenario}")
    canonical = ROOT / "results/phase7/io_vnbd/s1"
    if args.output_dir:
        output = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    elif args.scenario:
        output = canonical / "reproductions" / args.scenario.lower()
    else:
        output = canonical
    (output / "benchmarks").mkdir(parents=True, exist_ok=True)
    (output / "plots").mkdir(parents=True, exist_ok=True)

    phase6 = load_json(phase7["phase6_config"])
    phase5 = load_json(phase7["phase5_config"])
    map_config = load_json(phase6["map_config"])
    phase4_settings = Phase4Settings.from_dict(load_json(phase7["phase4_config"]))
    hybrid_settings = HybridSettings.from_dict(load_json(phase5["ekf_config"]))
    settings = Phase7Config.from_dict(phase7["settings"])
    bundle = load_velocity_bundle(ROOT / phase5["checkpoint_path"])
    graph = RoadGraph.load(ROOT / map_config["cache_path"])
    matcher = MapMatcherConfig.from_dict(phase6["matcher"])
    journey = load_journey("S1", project_root_path=ROOT)
    before = {"smartphone": sha256_file(journey.smartphone_path), "vbox_reference": sha256_file(journey.vehicle_path)}
    summary_rows: list[dict[str, Any]] = []
    evaluations: dict[str, Any] = {}
    runs: dict[str, Any] = {}
    for scenario in selected:
        window = BlackoutWindow(float(scenario["start_s"]), float(scenario["duration_s"]))
        experiment = create_blackout_experiment(journey, window)
        run = run_phase7_runtime(
            experiment.runtime, window, phase4_settings, hybrid_settings,
            bundle, graph, matcher, settings,
        )
        evaluation = evaluate_phase7_runtime(run, experiment.reference)
        metrics = evaluation.metrics
        expected = float(phase7["locked_phase6_drift_pct"][scenario["id"]])
        actual = float(metrics["blackout_final_idr_drift_pct"])
        metrics["locked_phase6_drift_pct"] = expected
        metrics["phase6_metric_difference_percentage_points"] = actual - expected
        metrics["phase6_metric_preserved"] = abs(actual - expected) < 1e-9
        if not metrics["phase6_metric_preserved"]:
            raise AssertionError(f"Frozen Phase 6 metric changed for {scenario['id']}: {actual} != {expected}")
        scenario_dir = output / "benchmarks" / scenario["id"].lower()
        scenario_dir.mkdir(parents=True, exist_ok=True)
        evaluation.timeseries.to_csv(scenario_dir / "timeseries.csv", index=False)
        save_json(scenario_dir / "result.json", {"scenario": scenario, "metrics": metrics, "startup_seconds": run.startup_seconds})
        summary_rows.append({
            "scenario": scenario["id"],
            "duration_s": window.duration_s,
            "phase6_drift_pct": actual,
            "blackout_final_idr_error_m": metrics["blackout_final_idr_error_m"],
            "fresh_fix_delay_s": metrics["fresh_fix_delay_after_blackout_s"],
            "stale_repeated_rejected": metrics["stale_repeated_fixes_rejected"],
            "candidate_rejected": metrics["candidate_reacquisition_fixes_rejected"],
            "fresh_fixes_to_verify": metrics["fresh_fixes_required_before_verification"],
            "hard_snap_jump_m": metrics["b1_first_fresh_fix_hard_snap_jump_m"],
            "p7_max_step_m": metrics["phase7_maximum_instantaneous_correction_m"],
            "max_correction_rate_mps": metrics["maximum_recovery_correction_rate_mps"],
            "recovery_duration_s": metrics["recovery_duration_s"],
            "time_to_active_s": metrics["time_to_return_gnss_active_s"],
            "post_rmse_m": metrics["post_reacquisition_rmse_m"],
            "post_p95_m": metrics["post_reacquisition_p95_m"],
            "final_post_error_m": metrics["final_post_recovery_error_m"],
            "phase6_preserved": metrics["phase6_metric_preserved"],
        })
        evaluations[scenario["id"]] = evaluation
        runs[scenario["id"]] = run
        print(pd.Series(summary_rows[-1]).to_string())
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(output / "benchmarks/summary.csv", index=False)
    save_json(output / "benchmarks/summary.json", summary_rows)
    if "S1_60_STOP_GO" in evaluations:
        representative_plots(evaluations["S1_60_STOP_GO"], runs["S1_60_STOP_GO"].window, output / "plots")
        representative = runs["S1_60_STOP_GO"]
        evaluation = evaluations["S1_60_STOP_GO"]
        samples = len(representative.data)
        blackout_samples = int(representative.data["is_blackout"].sum())
        phase5_ms = representative.startup_seconds["phase5_span_processing"] / samples * 1000
        phase6_ms = representative.startup_seconds["phase6_blackout_map_matching"] / blackout_samples * 1000
        phase7_ms = float(np.mean(representative.online_latency_ms))
        combined_ms = phase5_ms + phase6_ms + phase7_ms
        performance = {
            "scope": "S1_60_STOP_GO warm loops; excludes dataset/model/map loading, road localization/index construction, VBOX evaluation, file output, and plots",
            "phase5_average_ms_per_sample": phase5_ms,
            "phase6_average_ms_per_blackout_sample": phase6_ms,
            "phase7_incremental_average_ms_per_sample": phase7_ms,
            "phase7_incremental_p50_ms": float(np.percentile(representative.online_latency_ms, 50)),
            "phase7_incremental_p95_ms": float(np.percentile(representative.online_latency_ms, 95)),
            "phase7_incremental_p99_ms": float(np.percentile(representative.online_latency_ms, 99)),
            "conservative_combined_average_ms_per_sample": combined_ms,
            "conservative_combined_samples_per_second": 1000.0 / combined_ms,
            "sustains_10_hz": combined_ms < 100.0,
            "note": "Combined tail estimate conservatively charges the Phase 6 blackout matcher on every sample; percentile timing is directly available for the incremental Phase 7 causal step.",
        }
        save_json(output / "performance.json", performance)
    after = {"smartphone": sha256_file(journey.smartphone_path), "vbox_reference": sha256_file(journey.vehicle_path)}
    manifest = {
        "schema_version": 1,
        "phase": 7,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "git_parent": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip(),
        "python_version": platform.python_version(),
        "configuration_status": phase7["status"],
        "selected_profile": phase7["selected_profile"],
        "held_out_used_for_tuning": False,
        "runtime_function_parameters": list(inspect.signature(run_phase7_runtime).parameters),
        "runtime_exclusions": ["VBOX/evaluation reference", "future GNSS", "future IMU", "planned route", "destination", "scenario ID", "benchmark truth"],
        "configuration_hashes": {"phase7": file_hash(phase7_path), "phase6": file_hash(phase7["phase6_config"]), "development": file_hash(phase7["development_config"])},
        "source_checksums_before": before,
        "source_checksums_after": after,
        "original_dataset_unchanged": before == after,
        "scenario_count": len(selected),
        "all_phase6_metrics_preserved": bool(summary["phase6_preserved"].all()),
    }
    save_json(output / "run_manifest.json", manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
