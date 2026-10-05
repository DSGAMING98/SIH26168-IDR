#!/usr/bin/env python3
"""Run the small Phase 6 development-only map-matcher comparison."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from idr.blackout import BlackoutWindow  # noqa: E402
from idr.calibrated_dr import Phase4Settings  # noqa: E402
from idr.hybrid.hybrid_idr import HybridSettings  # noqa: E402
from idr.io_vnbd import load_journey  # noqa: E402
from idr.map_matching import MapMatcherConfig, ProbabilisticMapMatcher, RoadGraph  # noqa: E402
from idr.map_matching.evaluation import evaluate_map_match  # noqa: E402
from idr.ml.velocity_model import load_velocity_bundle  # noqa: E402
from idr.phase5_pipeline import run_phase5_scenario  # noqa: E402


def _json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    source = source if source.is_absolute() else ROOT / source
    return json.loads(source.read_text(encoding="utf-8"))


def _metric_row(dev_id: str, profile: str, prior_name: str, evaluation: Any) -> dict[str, Any]:
    metrics = evaluation.metrics
    return {
        "development_interval": dev_id,
        "profile": profile,
        "input_prior": prior_name,
        "drift_percentage": metrics["drift_percentage"],
        "final_position_error_m": metrics["final_position_error_m"],
        "mean_position_error_m": metrics["mean_position_error_m"],
        "rmse_m": metrics["rmse_position_error_m"],
        "mean_map_correction_m": metrics["mean_map_correction_m"],
        "maximum_map_correction_m": metrics["maximum_map_correction_m"],
        "mean_candidate_count": metrics["mean_candidate_count"],
        "ambiguous_sample_fraction": metrics["ambiguous_sample_fraction"],
        "no_candidate_fraction": metrics["no_candidate_fraction"],
        "road_switch_count": metrics["road_switch_count"],
        "map_matching_samples_per_second": metrics["map_matching_samples_per_second"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="results/phase6/io_vnbd/s1/development")
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    output_dir = output_dir if output_dir.is_absolute() else ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    phase6 = _json("configs/phase6/io_vnbd_s1_phase6.json")
    validation = _json(phase6["development_config"])
    phase5 = _json(phase6["phase5_config"])
    phase4_settings = Phase4Settings.from_dict(_json(phase6["phase4_config"]))
    hybrid_settings = HybridSettings.from_dict(_json(phase5["ekf_config"]))
    model_bundle = load_velocity_bundle(ROOT / phase5["checkpoint_path"])
    map_config = _json(phase6["map_config"])
    road_graph = RoadGraph.load(ROOT / map_config["cache_path"])
    journey = load_journey("S1", project_root_path=ROOT)
    rows: list[dict[str, Any]] = []
    base_settings = phase6["matcher"]
    for interval in validation["development_intervals"]:
        run = run_phase5_scenario(
            journey,
            BlackoutWindow(float(interval["start_s"]), float(interval["duration_s"])),
            phase4_settings,
            hybrid_settings,
            model_bundle,
        )
        origin = run.ekf_prediction.calibration.initialization
        local_graph = road_graph.localize(
            origin.origin_latitude_deg,
            origin.origin_longitude_deg,
            float(base_settings["grid_cell_size_m"]),
        )
        priors = {
            "E1_EKF_CLASSICAL": run.ekf_prediction,
            "H1_HYBRID_EKF_ML": run.hybrid_prediction,
        }
        for profile in validation["small_validation_comparison"]:
            settings = MapMatcherConfig.from_dict({**base_settings, **profile["overrides"]})
            matcher = ProbabilisticMapMatcher(local_graph, settings)
            for prior_name, prior in priors.items():
                match = matcher.match(prior.data, prior_name)
                evaluation = evaluate_map_match(match, prior, run.experiment.reference)
                rows.append(_metric_row(interval["id"], profile["id"], prior_name, evaluation))
    summary = pd.DataFrame(rows)
    summary.to_csv(output_dir / "validation_summary.csv", index=False)
    aggregates = (
        summary.groupby(["profile", "input_prior"], as_index=False)
        .agg(
            mean_drift_percentage=("drift_percentage", "mean"),
            median_drift_percentage=("drift_percentage", "median"),
            mean_rmse_m=("rmse_m", "mean"),
            mean_map_correction_m=("mean_map_correction_m", "mean"),
            maximum_map_correction_m=("maximum_map_correction_m", "max"),
            mean_candidate_count=("mean_candidate_count", "mean"),
            mean_ambiguous_fraction=("ambiguous_sample_fraction", "mean"),
            mean_no_candidate_fraction=("no_candidate_fraction", "mean"),
            mean_throughput_samples_per_second=("map_matching_samples_per_second", "mean"),
        )
        .sort_values(["mean_drift_percentage", "mean_rmse_m"])
        .reset_index(drop=True)
    )
    payload = {
        "schema_version": 1,
        "phase": 6,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "reference_policy": "VBOX used only by this development evaluator after estimator and map matching completed.",
        "held_out_used_for_selection": False,
        "intervals": validation["development_intervals"],
        "profiles": validation["small_validation_comparison"],
        "runs": summary.to_dict(orient="records"),
        "aggregate": aggregates.to_dict(orient="records"),
        "recommended_by_mean_dev_drift": aggregates.iloc[0].to_dict(),
    }
    (output_dir / "validation_summary.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    print(aggregates.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
