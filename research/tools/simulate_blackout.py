#!/usr/bin/env python3
"""Generate deterministic, leakage-resistant IO-VNBD blackout artifacts."""

from __future__ import annotations

import argparse
import json
import sys
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

from idr.blackout import (  # noqa: E402
    GNSS_DERIVED_FIELDS,
    RUNTIME_SENSOR_FIELDS,
    BlackoutWindow,
    create_blackout_experiment,
    scenario_characteristics,
    validate_experiment,
)
from idr.io_vnbd import load_journey, sha256_file  # noqa: E402


COLORS = ("#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00")


def _style(axis: Any) -> None:
    axis.grid(True, color="#D9DEE5", linewidth=0.6, alpha=0.8)
    axis.spines[["top", "right"]].set_visible(False)


def _save(figure: Any, path: Path) -> None:
    figure.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def _trajectory_plot(experiment: Any, scenario_id: str, output: Path) -> None:
    reference = experiment.reference.data
    blackout = reference["is_blackout"].to_numpy(dtype=bool)
    segment = reference.loc[blackout]
    figure, axis = plt.subplots(figsize=(8.5, 7.0))
    axis.plot(reference["longitude_deg"], reference["latitude_deg"], color="#B5BBC4", linewidth=0.9, label="Complete VBOX reference")
    axis.plot(segment["longitude_deg"], segment["latitude_deg"], color="#D55E00", linewidth=2.3, label="Hidden blackout segment")
    axis.scatter(segment["longitude_deg"].iloc[0], segment["latitude_deg"].iloc[0], s=55, color="#009E73", marker="o", label="Blackout start", zorder=4)
    axis.scatter(segment["longitude_deg"].iloc[-1], segment["latitude_deg"].iloc[-1], s=65, color="#7A5195", marker="X", label="Blackout end", zorder=4)
    axis.set_title(f"{scenario_id}: controlled GNSS blackout", loc="left", weight="bold")
    axis.set_xlabel("Longitude (degrees; datum/EPSG not stated)")
    axis.set_ylabel("Latitude (degrees; datum/EPSG not stated)")
    longitude_span = float(segment["longitude_deg"].max() - segment["longitude_deg"].min())
    latitude_span = float(segment["latitude_deg"].max() - segment["latitude_deg"].min())
    longitude_margin = max(longitude_span * 0.20, 0.00025)
    latitude_margin = max(latitude_span * 0.20, 0.00025)
    axis.set_xlim(float(segment["longitude_deg"].min()) - longitude_margin, float(segment["longitude_deg"].max()) + longitude_margin)
    axis.set_ylim(float(segment["latitude_deg"].min()) - latitude_margin, float(segment["latitude_deg"].max()) + latitude_margin)
    axis.set_aspect("equal", adjustable="box")
    axis.legend(frameon=False, loc="best")
    _style(axis)
    _save(figure, output)


def _overview_plot(journey: Any, scenarios: list[dict[str, Any]], output: Path) -> None:
    reference = journey.vehicle
    elapsed = journey.smartphone["elapsed_s"].to_numpy(dtype=float)
    figure, axis = plt.subplots(figsize=(9.0, 7.5))
    axis.plot(reference["longitude_deg"], reference["latitude_deg"], color="#B5BBC4", linewidth=0.8, label="Complete VBOX reference")
    for color, scenario in zip(COLORS, scenarios, strict=False):
        if not scenario.get("standard", True):
            continue
        mask = (elapsed >= float(scenario["start_s"])) & (elapsed < float(scenario["start_s"]) + float(scenario["duration_s"]))
        segment = reference.loc[mask]
        axis.plot(segment["longitude_deg"], segment["latitude_deg"], color=color, linewidth=2.7, label=scenario["id"])
        axis.scatter(segment["longitude_deg"].iloc[0], segment["latitude_deg"].iloc[0], color=color, s=30, zorder=4)
    axis.set_title("IO-VNBD S1: standard blackout benchmark locations", loc="left", weight="bold")
    axis.set_xlabel("Longitude (degrees; datum/EPSG not stated)")
    axis.set_ylabel("Latitude (degrees; datum/EPSG not stated)")
    axis.set_aspect("equal", adjustable="datalim")
    axis.legend(frameon=False, fontsize=8)
    _style(axis)
    _save(figure, output)


def _timeline_plot(experiment: Any, scenario_id: str, output: Path) -> None:
    runtime = experiment.runtime.sensor_data
    metadata = experiment.metadata
    display_start = max(float(runtime["elapsed_s"].iloc[0]), metadata.requested_start_s - 15.0)
    display_end = min(float(runtime["elapsed_s"].iloc[-1]), metadata.requested_end_s_exclusive + 15.0)
    view = runtime[(runtime["elapsed_s"] >= display_start) & (runtime["elapsed_s"] <= display_end)]
    figure, axes = plt.subplots(3, 1, figsize=(11.5, 7.5), sharex=True, gridspec_kw={"height_ratios": [0.7, 1.0, 1.0]})
    axes[0].step(view["elapsed_s"], view["gnss_available"].astype(int), where="post", color="#0072B2", linewidth=1.4)
    axes[0].set_yticks([0, 1], ["BLACKOUT", "AVAILABLE"])
    axes[0].set_ylim(-0.25, 1.25)
    axes[0].set_ylabel("GNSS")
    axes[1].plot(view["elapsed_s"], view["gyroscope_z_radps"], color="#D55E00", linewidth=0.8)
    axes[1].set_ylabel("Gyro Z\n(rad/s)")
    axes[2].plot(view["elapsed_s"], view["accelerometer_x_mps2"], color="#009E73", linewidth=0.8)
    axes[2].set_ylabel("Accel X\n(m/s²)")
    axes[2].set_xlabel("Synchronized elapsed session time (s)")
    for axis in axes:
        axis.axvspan(metadata.requested_start_s, metadata.requested_end_s_exclusive, color="#F4A6A6", alpha=0.3, label="Requested blackout")
        _style(axis)
    axes[0].set_title(f"{scenario_id}: runtime blackout and retained IMU signals", loc="left", weight="bold")
    axes[0].legend(frameon=False, loc="upper right")
    figure.tight_layout()
    _save(figure, output)


def _scenario_summary(journey: Any, scenario: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    experiment = create_blackout_experiment(
        journey,
        BlackoutWindow(float(scenario["start_s"]), float(scenario["duration_s"])),
    )
    checks = validate_experiment(journey, experiment)
    scenario_id = str(scenario["id"])
    mask_path = output_dir / "runtime" / f"{scenario_id.lower()}_runtime_mask.csv"
    mask_path.parent.mkdir(parents=True, exist_ok=True)
    experiment.runtime.sensor_data.loc[:, ["elapsed_s", "gnss_available"]].to_csv(mask_path, index=False)
    blackout_runtime_path = output_dir / "runtime" / f"{scenario_id.lower()}_blackout_runtime.csv"
    experiment.runtime.sensor_data.loc[
        ~experiment.runtime.sensor_data["gnss_available"]
    ].to_csv(blackout_runtime_path, index=False)
    trajectory_path = output_dir / "plots" / f"{scenario_id.lower()}_trajectory.png"
    trajectory_path.parent.mkdir(parents=True, exist_ok=True)
    _trajectory_plot(experiment, scenario_id, trajectory_path)
    return {
        "id": scenario_id,
        "type": scenario.get("type", "unclassified"),
        "standard": bool(scenario.get("standard", False)),
        "selection_evidence": scenario.get("selection_evidence", "User-specified custom interval."),
        "metadata": experiment.metadata.to_dict(),
        "reference_characteristics": scenario_characteristics(experiment),
        "validation": checks,
        "runtime_representation": {
            "aligned_mask": str(mask_path.relative_to(ROOT)).replace("\\", "/"),
            "blackout_sensor_frame": str(blackout_runtime_path.relative_to(ROOT)).replace("\\", "/"),
        },
        "trajectory_plot": str(trajectory_path.relative_to(ROOT)).replace("\\", "/"),
        "model_metrics": None,
    }


def _write_outputs(journey: Any, scenarios: list[dict[str, Any]], output_dir: Path, config_source: str | None) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    source_hashes_before = {
        "smartphone_sha256": sha256_file(journey.smartphone_path),
        "vehicle_reference_sha256": sha256_file(journey.vehicle_path),
    }
    summaries = [_scenario_summary(journey, scenario, output_dir) for scenario in scenarios]
    standard_scenarios = [scenario for scenario in scenarios if scenario.get("standard", False)]
    if standard_scenarios:
        overview_path = output_dir / "plots" / "s1_blackout_benchmark_overview.png"
        _overview_plot(journey, standard_scenarios, overview_path)
    representative = next((scenario for scenario in scenarios if scenario["id"] == "S1_60_STOP_GO"), scenarios[0])
    representative_experiment = create_blackout_experiment(journey, BlackoutWindow(float(representative["start_s"]), float(representative["duration_s"])))
    _timeline_plot(representative_experiment, str(representative["id"]), output_dir / "plots" / f"{str(representative['id']).lower()}_timeline.png")
    source_hashes_after = {
        "smartphone_sha256": sha256_file(journey.smartphone_path),
        "vehicle_reference_sha256": sha256_file(journey.vehicle_path),
    }
    if source_hashes_before != source_hashes_after:
        raise AssertionError("Original dataset file checksums changed during blackout generation.")
    top_level = {
        "phase": 2,
        "dataset": "IO-VNBD",
        "session": journey.session_id,
        "configuration_source": config_source,
        "data_domains": {
            "runtime_input": "RuntimeDataset(sensor_data, gnss_observations); aligned sensor_data contains no GNSS-derived fields and gnss_observations omits blackout rows.",
            "hidden_evaluation_reference": "EvaluationReference containing VBOX data; used only by validation and plotting.",
            "experiment_metadata": "Blackout bounds, timing, field policy, scenario label, and validation results; no hidden trajectory samples."
        },
        "blackout_semantics": "Half-open: start_s <= elapsed_s < start_s + duration_s",
        "gnss_derived_fields_hidden": list(GNSS_DERIVED_FIELDS),
        "runtime_sensor_fields": [*RUNTIME_SENSOR_FIELDS, "gnss_available"],
        "source_integrity": {"before": source_hashes_before, "after": source_hashes_after, "unchanged": True},
        "estimator_implemented": False,
        "scenarios": summaries,
    }
    (output_dir / "blackout_summary.json").write_text(json.dumps(top_level, indent=2), encoding="utf-8")
    rows: list[dict[str, Any]] = []
    for summary in summaries:
        rows.append({"id": summary["id"], "type": summary["type"], "standard": summary["standard"], **summary["metadata"], **summary["reference_characteristics"]})
    pd.DataFrame(rows).to_csv(output_dir / "blackout_summary.csv", index=False)
    runtime_schema = {
        "sensor_data_columns": [*RUNTIME_SENSOR_FIELDS, "gnss_available"],
        "gnss_observation_columns": ["elapsed_s", *GNSS_DERIVED_FIELDS],
        "blackout_behavior": "GNSS rows in the half-open blackout interval are removed from gnss_observations; sensor_data remains aligned and GNSS-free.",
        "reference_access": "Not part of RuntimeDataset; available only through ExperimentDataset.reference for evaluation/visualization.",
    }
    (output_dir / "runtime_schema.json").write_text(json.dumps(runtime_schema, indent=2), encoding="utf-8")
    return summaries


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", default="S1", help="Validated IO-VNBD session (currently S1).")
    parser.add_argument("--start", type=float, help="Blackout start in synchronized elapsed seconds.")
    parser.add_argument("--duration", type=float, help="Positive blackout duration in seconds.")
    parser.add_argument("--scenario-id", help="Identifier for one custom blackout.")
    parser.add_argument("--scenario-type", default="custom", help="Neutral signal-based label for one custom blackout.")
    parser.add_argument("--config", type=Path, help="JSON benchmark configuration. Cannot be combined with --start/--duration.")
    parser.add_argument("--output-dir", type=Path, help="Output directory; defaults below results/blackouts/io_vnbd/<session>.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.config is not None and (args.start is not None or args.duration is not None):
        raise SystemExit("--config cannot be combined with --start or --duration.")
    if args.config is None and (args.start is None or args.duration is None):
        raise SystemExit("Supply --config, or supply both --start and --duration.")
    journey = load_journey(args.session, project_root_path=ROOT)
    config_source: str | None = None
    if args.config is not None:
        config_path = args.config if args.config.is_absolute() else ROOT / args.config
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if str(config["session"]).upper() != journey.session_id:
            raise SystemExit("Configuration session does not match --session.")
        scenarios = list(config["scenarios"])
        config_source = str(config_path.relative_to(ROOT)).replace("\\", "/")
    else:
        duration_label = f"{float(args.duration):g}".replace(".", "p")
        scenarios = [{
            "id": args.scenario_id or f"{journey.session_id}_{duration_label}_CUSTOM",
            "start_s": float(args.start),
            "duration_s": float(args.duration),
            "type": args.scenario_type,
            "standard": False,
            "selection_evidence": "User-specified custom interval.",
        }]
    output_dir = args.output_dir or ROOT / "results" / "blackouts" / "io_vnbd" / journey.session_id.lower()
    resolved_output_dir = output_dir.resolve()
    summaries = _write_outputs(journey, scenarios, resolved_output_dir, config_source)
    if args.config is not None:
        (resolved_output_dir / "benchmark_config.json").write_text(
            json.dumps(config, indent=2), encoding="utf-8"
        )
    for summary in summaries:
        characteristics = summary["reference_characteristics"]
        print(f"{summary['id']}: {summary['metadata']['masked_sample_count']} samples, {summary['metadata']['actual_masked_duration_s']:.3f} s actual, {characteristics['reference_distance_m']:.3f} m VBOX reference distance")
    print(f"Wrote Phase 2 outputs to {resolved_output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
