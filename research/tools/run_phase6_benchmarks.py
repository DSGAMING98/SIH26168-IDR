#!/usr/bin/env python3
"""Run frozen Phase 6 map matching on held-out or custom S1 blackouts."""

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
from matplotlib.collections import LineCollection  # noqa: E402
from matplotlib.patches import Circle  # noqa: E402
import torch  # noqa: E402

from idr.blackout import BlackoutWindow  # noqa: E402
from idr.calibrated_dr import Phase4Settings  # noqa: E402
from idr.evaluation import geodetic_to_local_xy_m  # noqa: E402
from idr.hybrid.hybrid_idr import HybridSettings  # noqa: E402
from idr.io_vnbd import load_journey, sha256_file  # noqa: E402
from idr.map_matching import MapMatcherConfig, RoadGraph  # noqa: E402
from idr.ml.velocity_model import load_velocity_bundle  # noqa: E402
from idr.phase6_pipeline import Phase6ScenarioRun, run_phase6_scenario  # noqa: E402


COLORS = {
    "road": "#C5C7CC",
    "reference": "#202124",
    "ekf": "#0072B2",
    "hybrid": "#009E73",
    "nearest": "#E69F00",
    "prob": "#CC33A1",
}


def _json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    source = source if source.is_absolute() else ROOT / source
    return json.loads(source.read_text(encoding="utf-8"))


def _sha256(path: Path | str) -> str:
    source = Path(path)
    source = source if source.is_absolute() else ROOT / source
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _save_json(path: Path, values: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, indent=2, default=_json_default) + "\n", encoding="utf-8")


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Cannot JSON encode {type(value).__name__}")


def _metric(metrics: dict[str, Any], name: str) -> float:
    value = metrics.get(name)
    return float(value) if value is not None else float("nan")


def _scenarios() -> list[dict[str, Any]]:
    blackouts = _json("configs/blackouts/io_vnbd_s1.json")
    phase4 = _json("configs/phase4/io_vnbd_s1_classical.json")
    split = _json("configs/phase5/io_vnbd_s1_split.json")
    scenarios = [dict(item) for item in blackouts["scenarios"] if item.get("standard")]
    scenarios.append(dict(phase4["custom_judge_scenario"]))
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
    return scenarios


def _evaluations(run: Phase6ScenarioRun) -> dict[str, Any]:
    return {
        "B0_RAW": run.phase5.raw_evaluation,
        "B1_PHASE4_V4": run.phase5.phase4_v4_evaluation,
        "B2_PHASE4_V5": run.phase5.phase4_v5_evaluation,
        "E1_EKF": run.phase5.ekf_evaluation,
        "H1_HYBRID": run.phase5.hybrid_evaluation,
        "N1_EKF_NEAREST": run.ekf_nearest_evaluation,
        "N2_HYBRID_NEAREST": run.hybrid_nearest_evaluation,
        "P1_EKF_PROB_MAP": run.ekf_probabilistic_evaluation,
        "P2_HYBRID_PROB_MAP": run.hybrid_probabilistic_evaluation,
    }


def _summary_row(scenario: dict[str, Any], run: Phase6ScenarioRun, selected_prior: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    evaluations = _evaluations(run)
    phase4_key = min(
        ("B1_PHASE4_V4", "B2_PHASE4_V5"),
        key=lambda key: _metric(evaluations[key].metrics, "final_position_error_m"),
    )
    phase5_key = min(
        ("E1_EKF", "H1_HYBRID"),
        key=lambda key: _metric(evaluations[key].metrics, "final_position_error_m"),
    )
    if selected_prior == "H1_HYBRID_EKF_ML":
        nearest_key, final_key = "N2_HYBRID_NEAREST", "P2_HYBRID_PROB_MAP"
    else:
        nearest_key, final_key = "N1_EKF_NEAREST", "P1_EKF_PROB_MAP"
    final_metrics = evaluations[final_key].metrics
    phase5_best_error = _metric(evaluations[phase5_key].metrics, "final_position_error_m")
    final_error = _metric(final_metrics, "final_position_error_m")
    improvement = 100.0 * (phase5_best_error - final_error) / phase5_best_error if phase5_best_error > 0 else float("nan")
    sample_count = int(final_metrics["sample_count"])
    row = {
        "scenario": scenario["id"],
        "scenario_type": scenario.get("type", "custom"),
        "start_s": float(scenario["start_s"]),
        "duration_s": float(scenario["duration_s"]),
        "sample_count": sample_count,
        "reference_distance_m": _metric(final_metrics, "reference_distance_m"),
        "raw_drift_pct": _metric(evaluations["B0_RAW"].metrics, "drift_percentage"),
        "phase4_best_variant": phase4_key,
        "phase4_best_drift_pct": _metric(evaluations[phase4_key].metrics, "drift_percentage"),
        "ekf_drift_pct": _metric(evaluations["E1_EKF"].metrics, "drift_percentage"),
        "hybrid_drift_pct": _metric(evaluations["H1_HYBRID"].metrics, "drift_percentage"),
        "nearest_road_drift_pct": _metric(evaluations[nearest_key].metrics, "drift_percentage"),
        "prob_map_ekf_drift_pct": _metric(evaluations["P1_EKF_PROB_MAP"].metrics, "drift_percentage"),
        "prob_map_hybrid_drift_pct": _metric(evaluations["P2_HYBRID_PROB_MAP"].metrics, "drift_percentage"),
        "final_phase6_variant": final_key,
        "final_phase6_drift_pct": _metric(final_metrics, "drift_percentage"),
        "final_error_m": final_error,
        "phase5_best_variant": phase5_key,
        "phase5_best_error_m": phase5_best_error,
        "improvement_vs_phase5_best_pct": improvement,
        "rmse_m": _metric(final_metrics, "rmse_position_error_m"),
        "p95_m": _metric(final_metrics, "p95_position_error_m"),
        "average_candidates": _metric(final_metrics, "mean_candidate_count"),
        "ambiguous_samples_pct": 100.0 * _metric(final_metrics, "ambiguous_sample_fraction"),
        "no_candidate_samples_pct": 100.0 * _metric(final_metrics, "no_candidate_fraction"),
        "mean_map_correction_m": _metric(final_metrics, "mean_map_correction_m"),
        "maximum_map_correction_m": _metric(final_metrics, "maximum_map_correction_m"),
        "road_switch_count": int(final_metrics["road_switch_count"]),
        "hypothesis_switch_count": int(final_metrics["hypothesis_switch_count"]),
        "impossible_transition_rejections": int(final_metrics["impossible_transition_rejections"]),
    }
    ablations = []
    for key, evaluation in evaluations.items():
        metrics = evaluation.metrics
        ablations.append(
            {
                "scenario": scenario["id"],
                "algorithm": key,
                "final_error_m": _metric(metrics, "final_position_error_m"),
                "mean_error_m": _metric(metrics, "mean_position_error_m"),
                "rmse_m": _metric(metrics, "rmse_position_error_m"),
                "p95_m": _metric(metrics, "p95_position_error_m"),
                "drift_pct": _metric(metrics, "drift_percentage"),
                "mean_map_correction_m": _metric(metrics, "mean_map_correction_m") if "mean_map_correction_m" in metrics else 0.0,
                "maximum_map_correction_m": _metric(metrics, "maximum_map_correction_m") if "maximum_map_correction_m" in metrics else 0.0,
                "road_switch_count": int(metrics.get("road_switch_count", 0)),
                "ambiguous_sample_fraction": _metric(metrics, "ambiguous_sample_fraction") if "ambiguous_sample_fraction" in metrics else 0.0,
                "no_candidate_fraction": _metric(metrics, "no_candidate_fraction") if "no_candidate_fraction" in metrics else 0.0,
            }
        )
    final_record = next(dict(item) for item in ablations if item["algorithm"] == final_key)
    final_record["algorithm"] = "FINAL_PHASE6"
    ablations.append(final_record)
    return row, ablations


def _reference_absolute_xy(run: Phase6ScenarioRun) -> np.ndarray:
    prediction = run.phase5.ekf_prediction.data
    reference = run.phase5.experiment.reference.data.set_index("runtime_elapsed_s")
    aligned = reference.loc[prediction["elapsed_s"].to_numpy(dtype=float)]
    origin = run.phase5.ekf_prediction.calibration.initialization
    local = geodetic_to_local_xy_m(
        aligned["latitude_deg"], aligned["longitude_deg"],
        origin.origin_latitude_deg, origin.origin_longitude_deg,
    )
    return np.column_stack((local.x_east_m, local.y_north_m))


def _road_segments(run: Phase6ScenarioRun, minimum: np.ndarray, maximum: np.ndarray) -> list[np.ndarray]:
    center = 0.5 * (minimum + maximum)
    radius = 0.5 * float(np.linalg.norm(maximum - minimum)) + 100.0
    return [
        run.local_road_graph.edges[edge_id].points_xy_m
        for edge_id in run.local_road_graph.nearby_edge_ids(center[0], center[1], max(radius, 25.0))
        if edge_id in run.local_road_graph.edges
    ]


def _style(axis: Any) -> None:
    axis.grid(alpha=0.2)
    axis.spines[["top", "right"]].set_visible(False)


def _save_figure(figure: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.tight_layout()
    figure.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(figure)


def _plot_trajectory(scenario_id: str, run: Phase6ScenarioRun, selected_prior: str, path: Path) -> None:
    reference = _reference_absolute_xy(run)
    if selected_prior == "H1_HYBRID_EKF_ML":
        prior = run.phase5.hybrid_prediction.data
        nearest = run.hybrid_nearest.data
        matched = run.hybrid_probabilistic.data
    else:
        prior = run.phase5.ekf_prediction.data
        nearest = run.ekf_nearest.data
        matched = run.ekf_probabilistic.data
    prior_xy = prior[["estimated_x_m", "estimated_y_m"]].to_numpy(dtype=float)
    nearest_xy = nearest[["matched_east_m", "matched_north_m"]].to_numpy(dtype=float)
    matched_xy = matched[["matched_east_m", "matched_north_m"]].to_numpy(dtype=float)
    all_xy = np.vstack((reference, prior_xy, nearest_xy, matched_xy))
    minimum, maximum = np.min(all_xy, axis=0) - 60, np.max(all_xy, axis=0) + 60
    figure, axis = plt.subplots(figsize=(8, 7))
    segments = _road_segments(run, minimum, maximum)
    axis.add_collection(LineCollection(segments, colors=COLORS["road"], linewidths=0.55, alpha=0.75, zorder=0))
    axis.plot(reference[:, 0], reference[:, 1], color=COLORS["reference"], lw=2.2, label="VBOX evaluation reference")
    axis.plot(prior_xy[:, 0], prior_xy[:, 1], color=COLORS["hybrid" if selected_prior.startswith("H1") else "ekf"], lw=1.5, label="Unconstrained Phase 5")
    axis.plot(nearest_xy[:, 0], nearest_xy[:, 1], color=COLORS["nearest"], lw=1.3, label="Nearest road")
    axis.plot(matched_xy[:, 0], matched_xy[:, 1], color=COLORS["prob"], lw=2.0, label="Probabilistic map match")
    axis.scatter(*matched_xy[0], marker="o", color="#2E7D32", s=45, label="Blackout start", zorder=5)
    axis.scatter(*matched_xy[-1], marker="X", color="#B71C1C", s=55, label="Blackout end", zorder=5)
    axis.set(xlim=(minimum[0], maximum[0]), ylim=(minimum[1], maximum[1]), xlabel="East (m)", ylabel="North (m)", title=f"{scenario_id}: static roads and blackout trajectories")
    axis.set_aspect("equal", adjustable="box")
    axis.legend(fontsize=8, loc="best")
    _style(axis)
    _save_figure(figure, path)


def _plot_error(scenario_id: str, run: Phase6ScenarioRun, selected_prior: str, path: Path) -> None:
    elapsed = run.phase5.ekf_evaluation.timeseries["blackout_elapsed_s"]
    final_eval = run.hybrid_probabilistic_evaluation if selected_prior.startswith("H1") else run.ekf_probabilistic_evaluation
    nearest_eval = run.hybrid_nearest_evaluation if selected_prior.startswith("H1") else run.ekf_nearest_evaluation
    figure, axis = plt.subplots(figsize=(8, 4.2))
    series = [
        ("EKF", run.phase5.ekf_evaluation.timeseries, COLORS["ekf"]),
        ("Hybrid", run.phase5.hybrid_evaluation.timeseries, COLORS["hybrid"]),
        ("Nearest road", nearest_eval.timeseries, COLORS["nearest"]),
        ("Probabilistic map", final_eval.timeseries, COLORS["prob"]),
    ]
    for label, frame, color in series:
        axis.plot(elapsed, frame["relative_position_error_m"], label=label, color=color, lw=1.5)
    axis.set(xlabel="Blackout elapsed time (s)", ylabel="Relative position error (m)", title=f"{scenario_id}: error through blackout")
    axis.legend(ncol=2, fontsize=8)
    _style(axis)
    _save_figure(figure, path)


def _plot_diagnostics(scenario_id: str, run: Phase6ScenarioRun, selected_prior: str, path: Path) -> None:
    match = run.hybrid_probabilistic.data if selected_prior.startswith("H1") else run.ekf_probabilistic.data
    elapsed = match["elapsed_s"] - match["elapsed_s"].iloc[0]
    figure, axes = plt.subplots(4, 1, figsize=(9, 9), sharex=True)
    axes[0].plot(elapsed, match["map_correction_m"], color=COLORS["prob"], lw=1.3)
    axes[0].axhline(10, color="#999999", ls="--", lw=0.8)
    axes[0].set_ylabel("Correction (m)")
    axes[1].plot(elapsed, match["top_probability"], label="Top", color="#2E7D32")
    axes[1].plot(elapsed, match["second_probability"], label="Second", color="#F57C00")
    axes[1].plot(elapsed, match["ambiguity_score"], label="Ambiguity", color="#6A1B9A", alpha=0.7)
    axes[1].set_ylabel("Probability / score")
    axes[1].legend(ncol=3, fontsize=8)
    axes[2].plot(elapsed, match["position_sigma_m"], label="Phase 5 σ", color=COLORS["ekf"])
    axes[2].plot(elapsed, match["candidate_search_radius_m"], label="Search radius", color="#D55E00")
    axes[2].set_ylabel("Metres")
    axes[2].legend(fontsize=8)
    axes[3].step(elapsed, match["candidate_count"], where="mid", label="Candidates", color="#444444")
    switch_times = elapsed[match["road_switch"].to_numpy(dtype=bool)]
    for switch_time in switch_times:
        axes[3].axvline(switch_time, color="#B71C1C", alpha=0.25, lw=0.7)
    axes[3].set(xlabel="Blackout elapsed time (s)", ylabel="Candidate count")
    for axis in axes:
        _style(axis)
    figure.suptitle(f"{scenario_id}: correction, ambiguity, uncertainty, and road switches")
    _save_figure(figure, path)


def _plot_candidate_view(scenario_id: str, run: Phase6ScenarioRun, selected_prior: str, path: Path) -> None:
    match = run.hybrid_probabilistic.data if selected_prior.startswith("H1") else run.ekf_probabilistic.data
    ambiguous = match["ambiguity_score"].to_numpy(dtype=float)
    index = int(np.argmax(ambiguous))
    row = match.iloc[index]
    center = np.array([row["prior_east_m"], row["prior_north_m"]], dtype=float)
    radius = float(row["candidate_search_radius_m"])
    edge_ids = run.local_road_graph.nearby_edge_ids(center[0], center[1], radius)
    figure, axis = plt.subplots(figsize=(7, 7))
    for edge_id in edge_ids:
        edge = run.local_road_graph.edges[edge_id]
        color, width, label = COLORS["road"], 1.0, None
        if edge_id == row["road_edge_id"]:
            color, width, label = COLORS["prob"], 3.0, f"Top: {row['top_probability']:.2f}"
        elif edge_id == row["second_edge_id"]:
            color, width, label = COLORS["nearest"], 2.5, f"Second: {row['second_probability']:.2f}"
        axis.plot(edge.points_xy_m[:, 0], edge.points_xy_m[:, 1], color=color, lw=width, label=label)
    axis.add_patch(Circle(center, radius, facecolor="#0072B2", edgecolor="#0072B2", alpha=0.08, lw=1.2))
    axis.scatter(center[0], center[1], marker="x", s=80, color=COLORS["ekf"], label="Phase 5 point")
    axis.scatter(row["matched_east_m"], row["matched_north_m"], marker="o", s=55, color=COLORS["prob"], label="Selected point")
    axis.set(xlim=(center[0] - radius, center[0] + radius), ylim=(center[1] - radius, center[1] + radius), xlabel="East (m)", ylabel="North (m)", title=f"{scenario_id}: ambiguity at t={row['elapsed_s'] - match['elapsed_s'].iloc[0]:.1f}s")
    axis.set_aspect("equal", adjustable="box")
    handles, labels = axis.get_legend_handles_labels()
    unique = dict(zip(labels, handles, strict=True))
    axis.legend(unique.values(), unique.keys(), fontsize=8)
    _style(axis)
    _save_figure(figure, path)


def _plot_drift(summary: pd.DataFrame, path: Path) -> None:
    columns = ["ekf_drift_pct", "hybrid_drift_pct", "nearest_road_drift_pct", "final_phase6_drift_pct"]
    labels = ["EKF", "Hybrid", "Nearest road", "ProbMap final"]
    x = np.arange(len(summary))
    width = 0.2
    figure, axis = plt.subplots(figsize=(11, 5))
    for index, (column, label) in enumerate(zip(columns, labels, strict=True)):
        axis.bar(x + (index - 1.5) * width, summary[column], width, label=label)
    axis.axhline(10, color="#B71C1C", ls="--", lw=1, label="10% target")
    axis.set_xticks(x, summary["scenario"], rotation=25, ha="right")
    axis.set(ylabel="Final drift (%)", title="Held-out Phase 5 and Phase 6 comparison")
    axis.legend(ncol=5, fontsize=8)
    _style(axis)
    _save_figure(figure, path)


def _judge_before_after(run: Phase6ScenarioRun, selected_prior: str, path: Path) -> None:
    reference = _reference_absolute_xy(run)
    prior = run.phase5.hybrid_prediction.data if selected_prior.startswith("H1") else run.phase5.ekf_prediction.data
    matched = run.hybrid_probabilistic.data if selected_prior.startswith("H1") else run.ekf_probabilistic.data
    prior_xy = prior[["estimated_x_m", "estimated_y_m"]].to_numpy(dtype=float)
    matched_xy = matched[["matched_east_m", "matched_north_m"]].to_numpy(dtype=float)
    all_xy = np.vstack((reference, prior_xy, matched_xy))
    minimum, maximum = np.min(all_xy, axis=0) - 50, np.max(all_xy, axis=0) + 50
    roads = _road_segments(run, minimum, maximum)
    figure, axes = plt.subplots(1, 2, figsize=(12, 5.5), sharex=True, sharey=True)
    for axis, xy, title, color in (
        (axes[0], prior_xy, "Before: sensor estimate drifts off-road", COLORS["hybrid"]),
        (axes[1], matched_xy, "After: connected road hypotheses constrain it", COLORS["prob"]),
    ):
        axis.add_collection(LineCollection(roads, colors=COLORS["road"], linewidths=0.6))
        axis.plot(reference[:, 0], reference[:, 1], color=COLORS["reference"], lw=2, label="Reference")
        axis.plot(xy[:, 0], xy[:, 1], color=color, lw=2, label="Estimate")
        axis.set(title=title, xlabel="East (m)", ylabel="North (m)", xlim=(minimum[0], maximum[0]), ylim=(minimum[1], maximum[1]))
        axis.set_aspect("equal", adjustable="box")
        axis.legend(fontsize=8)
        _style(axis)
    figure.suptitle("No planned route: motion, uncertainty, and topology choose the road")
    _save_figure(figure, path)


def _combined_timeseries(run: Phase6ScenarioRun, selected_prior: str) -> pd.DataFrame:
    final_eval = run.hybrid_probabilistic_evaluation if selected_prior.startswith("H1") else run.ekf_probabilistic_evaluation
    nearest_eval = run.hybrid_nearest_evaluation if selected_prior.startswith("H1") else run.ekf_nearest_evaluation
    output = final_eval.timeseries.copy()
    output["ekf_relative_error_m"] = run.phase5.ekf_evaluation.timeseries["relative_position_error_m"].to_numpy()
    output["hybrid_relative_error_m"] = run.phase5.hybrid_evaluation.timeseries["relative_position_error_m"].to_numpy()
    output["nearest_relative_error_m"] = nearest_eval.timeseries["relative_position_error_m"].to_numpy()
    output["prob_map_ekf_relative_error_m"] = run.ekf_probabilistic_evaluation.timeseries["relative_position_error_m"].to_numpy()
    output["prob_map_hybrid_relative_error_m"] = run.hybrid_probabilistic_evaluation.timeseries["relative_position_error_m"].to_numpy()
    return output


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", help="Configured scenario ID")
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
    phase6_path = ROOT / "configs/phase6/io_vnbd_s1_phase6.json"
    phase6 = _json(phase6_path)
    if phase6.get("status") != "frozen_before_held_out_evaluation":
        raise SystemExit("Phase 6 configuration is not frozen; held-out evaluation refused.")
    scenarios = _scenarios()
    selected_run = bool(args.scenario or args.start is not None)
    if args.scenario:
        scenarios = [item for item in scenarios if item["id"].upper() == args.scenario.upper()]
        if not scenarios:
            raise SystemExit(f"Scenario not found: {args.scenario}")
    elif args.start is not None:
        scenarios = [{
            "id": args.scenario_id or f"{args.session}_{args.duration:g}_PHASE6_CUSTOM",
            "start_s": float(args.start), "duration_s": float(args.duration), "type": "custom_phase6",
        }]
    canonical = ROOT / "results/phase6/io_vnbd/s1"
    if args.output_dir:
        output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    elif selected_run:
        output_dir = canonical / "reproductions" / scenarios[0]["id"].lower()
    else:
        output_dir = canonical
    for name in ("benchmarks", "ablations", "diagnostics", "plots"):
        (output_dir / name).mkdir(parents=True, exist_ok=True)

    phase5_config = _json(phase6["phase5_config"])
    phase4_settings = Phase4Settings.from_dict(_json(phase6["phase4_config"]))
    hybrid_settings = HybridSettings.from_dict(_json(phase5_config["ekf_config"]))
    bundle = load_velocity_bundle(ROOT / phase5_config["checkpoint_path"])
    map_config = _json(phase6["map_config"])
    road_graph = RoadGraph.load(ROOT / map_config["cache_path"])
    map_settings = MapMatcherConfig.from_dict(phase6["matcher"])
    journey = load_journey(args.session, project_root_path=ROOT)
    source_before = {"smartphone": sha256_file(journey.smartphone_path), "vbox_reference": sha256_file(journey.vehicle_path)}
    selected_prior = phase6["selected_input_estimator"]
    summary_rows: list[dict[str, Any]] = []
    ablation_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    hypothesis_rows: list[dict[str, Any]] = []
    correction_rows: list[dict[str, Any]] = []
    scenario_payloads: list[dict[str, Any]] = []
    performance = {"samples": 0, "candidate_seconds": 0.0, "matching_seconds": 0.0, "full_seconds": 0.0}
    started_all = time.perf_counter()
    for scenario in scenarios:
        run = run_phase6_scenario(
            journey,
            BlackoutWindow(float(scenario["start_s"]), float(scenario["duration_s"])),
            phase4_settings, hybrid_settings, bundle, road_graph, map_settings,
        )
        row, ablations = _summary_row(scenario, run, selected_prior)
        summary_rows.append(row)
        ablation_rows.extend(ablations)
        scenario_id = scenario["id"].lower()
        final_match = run.hybrid_probabilistic if selected_prior.startswith("H1") else run.ekf_probabilistic
        final_evaluation = run.hybrid_probabilistic_evaluation if selected_prior.startswith("H1") else run.ekf_probabilistic_evaluation
        timeseries = _combined_timeseries(run, selected_prior)
        scenario_dir = output_dir / "benchmarks" / scenario_id
        scenario_dir.mkdir(parents=True, exist_ok=True)
        timeseries.to_csv(scenario_dir / "timeseries.csv", index=False)
        result_payload = {"scenario": scenario, "summary": row, "final_metrics": final_evaluation.metrics}
        _save_json(scenario_dir / "result.json", result_payload)
        scenario_payloads.append(result_payload)
        for variant, match, evaluation in (
            ("EKF_NEAREST", run.ekf_nearest, run.ekf_nearest_evaluation),
            ("HYBRID_NEAREST", run.hybrid_nearest, run.hybrid_nearest_evaluation),
            ("EKF_PROB_MAP", run.ekf_probabilistic, run.ekf_probabilistic_evaluation),
            ("HYBRID_PROB_MAP", run.hybrid_probabilistic, run.hybrid_probabilistic_evaluation),
        ):
            metrics = evaluation.metrics
            candidate_rows.append({"scenario": scenario["id"], "variant": variant, "mean_candidates": metrics["mean_candidate_count"], "maximum_candidates": metrics["maximum_candidate_count"], "mean_radius_m": metrics["mean_candidate_search_radius_m"], "maximum_radius_m": metrics["maximum_candidate_search_radius_m"], "no_candidate_count": metrics["no_candidate_count"]})
            hypothesis_rows.append({"scenario": scenario["id"], "variant": variant, "road_switch_count": metrics["road_switch_count"], "hypothesis_switch_count": metrics["hypothesis_switch_count"], "ambiguous_sample_count": metrics["ambiguous_sample_count"], "mean_top_probability": metrics["mean_top_candidate_probability"], "impossible_transition_rejections": metrics["impossible_transition_rejections"]})
            correction_rows.append({"scenario": scenario["id"], "variant": variant, "mean_correction_m": metrics["mean_map_correction_m"], "maximum_correction_m": metrics["maximum_map_correction_m"], "above_10m": metrics["corrections_above_10m"], "above_25m": metrics["corrections_above_25m"], "above_50m": metrics["corrections_above_50m"]})
        performance["samples"] += len(final_match.data)
        performance["candidate_seconds"] += final_match.candidate_generation_seconds
        performance["matching_seconds"] += final_match.matching_seconds
        phase5_seconds = run.phase5.processing_seconds["hybrid" if selected_prior.startswith("H1") else "ekf"]
        performance["full_seconds"] += phase5_seconds + final_match.matching_seconds + run.road_graph_localization_seconds
        _plot_trajectory(scenario["id"], run, selected_prior, output_dir / "plots" / f"{scenario_id}_road_trajectory.png")
        _plot_error(scenario["id"], run, selected_prior, output_dir / "plots" / f"{scenario_id}_error_vs_time.png")
        _plot_diagnostics(scenario["id"], run, selected_prior, output_dir / "plots" / f"{scenario_id}_map_diagnostics.png")
        if scenario["id"] == "S1_30_TURNING":
            _plot_candidate_view(scenario["id"], run, selected_prior, output_dir / "plots" / "s1_30_turning_candidate_hypotheses.png")
        if scenario["id"] == "S1_60_STOP_GO":
            _judge_before_after(run, selected_prior, output_dir / "plots" / "s1_60_stop_go_before_after.png")

    summary = pd.DataFrame(summary_rows)
    ablation = pd.DataFrame(ablation_rows)
    summary.to_csv(output_dir / "benchmarks/summary.csv", index=False)
    ablation.to_csv(output_dir / "ablations/map_ablation.csv", index=False)
    pd.DataFrame(candidate_rows).to_csv(output_dir / "diagnostics/candidate_stats.csv", index=False)
    pd.DataFrame(hypothesis_rows).to_csv(output_dir / "diagnostics/hypothesis_stats.csv", index=False)
    pd.DataFrame(correction_rows).to_csv(output_dir / "diagnostics/correction_stats.csv", index=False)
    _save_json(output_dir / "benchmarks/summary.json", scenario_payloads)
    _save_json(output_dir / "ablations/map_ablation.json", ablation_rows)
    _plot_drift(summary, output_dir / "plots/drift_comparison.png")
    map_metadata = _json(map_config["metadata_path"])
    throughput = {
        "candidate_generation_samples_per_second": performance["samples"] / max(performance["candidate_seconds"], 1e-12),
        "probabilistic_map_matching_samples_per_second": performance["samples"] / max(performance["matching_seconds"], 1e-12),
        "phase5_plus_phase6_samples_per_second": performance["samples"] / max(performance["full_seconds"], 1e-12),
        "input_rate_hz": 10.0,
        "comfortably_exceeds_input_rate": performance["samples"] / max(performance["full_seconds"], 1e-12) > 20.0,
        "road_graph_nodes": len(road_graph.nodes),
        "road_graph_directed_edges": len(road_graph.edges),
        "map_cache_size_bytes": map_metadata["cache_size_bytes"],
        "wall_seconds": time.perf_counter() - started_all,
    }
    source_after = {"smartphone": sha256_file(journey.smartphone_path), "vbox_reference": sha256_file(journey.vehicle_path)}
    manifest = {
        "schema_version": 1,
        "phase": 6,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "git_parent": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip(),
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "torch_version": torch.__version__,
        "selected_input_estimator": selected_prior,
        "selected_profile": phase6["selected_profile"],
        "held_out_used_for_tuning": False,
        "runtime_inputs": ["Phase 5 estimator output", "static local OSM road cache", "frozen experiment metadata"],
        "runtime_exclusions": ["VBOX/evaluation reference", "phone GNSS at or after blackout start", "planned route", "destination", "scenario truth"],
        "configuration_hashes": {
            "phase6": _sha256(phase6_path),
            "map": _sha256(phase6["map_config"]),
            "development": _sha256(phase6["development_config"]),
            "phase4": _sha256(phase6["phase4_config"]),
            "phase5": _sha256(phase6["phase5_config"]),
            "map_cache": map_metadata["cache_sha256"],
        },
        "source_checksums_before": source_before,
        "source_checksums_after": source_after,
        "original_dataset_unchanged": source_before == source_after,
        "performance": throughput,
        "scenario_count": len(summary),
    }
    _save_json(output_dir / "run_manifest.json", manifest)
    _save_json(output_dir / "map_cache_manifest.json", map_metadata)
    _save_json(output_dir / "map_split_manifest.json", _json(phase6["development_config"]))
    print(summary.to_string(index=False))
    print(json.dumps(throughput, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
