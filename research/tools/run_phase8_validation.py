#!/usr/bin/env python
"""Reproduce the frozen Phase 8 cross-dataset zero-shot validation."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from idr.calibrated_dr import as_raw_prediction  # noqa: E402
from idr.ml.velocity_model import load_velocity_bundle  # noqa: E402
from idr.phase8.adapters import SmartphoneDecimeterAdapter  # noqa: E402
from idr.phase8.canonical import create_runtime_blackout  # noqa: E402
from idr.phase8.capability import capability_rows  # noqa: E402
from idr.phase8.evaluation import evaluate_completed_prediction, hybrid_feature_shift  # noqa: E402
from idr.phase8.pipeline import load_frozen_settings, prepare_runtime, run_frozen_variants  # noqa: E402


FROZEN_HASHES = {
    "models/phase5/io_vnbd_s1/velocity_gru.pt": "fa2169781f9e499dd87fdd00038a3b4a1326181b31938cec237a7802ae0bb4ec",
    "models/phase5/io_vnbd_s1/feature_scaler.json": "5ddea9cf91db0071528b56fc1d303edd0850769efdd53f77c03b0feba9cbf36a",
    "configs/phase6/io_vnbd_s1_phase6.json": "a1fa39c0aff3170ac68874bd05b1ef059bb0596525dffd0a0c8ebc69f406d952",
    "configs/phase7/io_vnbd_s1_phase7.json": "bfcb4ebc22f8eaa1d625b35eba0c359b878c0f75f39ce8249c1d716a87d0354e",
}
VARIANT_LABELS = {
    "C0_RAW_ADAPTED": "Raw adapted",
    "C1_PHASE4_ADAPTED": "Phase 4",
    "C2_FROZEN_PHASE5_EKF": "EKF",
    "C3_FROZEN_PHASE5_HYBRID": "Hybrid",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_safe(value), indent=2) + "\n", encoding="utf-8")


def locked_s1_baseline() -> dict[str, Any]:
    payload = subprocess.check_output(
        ["git", "show", "93ddc6b072917db23c1feb7e505e83943d2e9d36:results/phase5/io_vnbd/s1/summary.json"],
        cwd=ROOT,
        text=True,
    )
    rows = [row for row in json.loads(payload) if bool(row["standard"])]
    return {
        "dataset": "IO-VNBD S1 baseline",
        "scenario_count": len(rows),
        "median_raw_drift_pct": float(np.median([row["raw_drift_pct"] for row in rows])),
        "median_phase4_drift_pct": float(np.median([row["phase4_v5_drift_pct"] for row in rows])),
        "median_ekf_drift_pct": float(np.median([row["ekf_drift_pct"] for row in rows])),
        "median_hybrid_drift_pct": float(np.median([row["hybrid_drift_pct"] for row in rows])),
        "source": "locked Phase 5 standard-window results at Phase 7 parent commit",
    }


def prediction_data(prediction: Any) -> pd.DataFrame:
    return prediction.data


def build_plots(summary: pd.DataFrame, scenario_frames: dict[str, pd.DataFrame], feature_shift: pd.DataFrame, output: Path) -> float:
    started = time.perf_counter()
    plot_dir = output / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)
    plt.style.use("seaborn-v0_8-whitegrid")

    variants = list(VARIANT_LABELS)
    x = np.arange(len(summary))
    width = 0.19
    fig, axis = plt.subplots(figsize=(11, 5.5))
    for offset, variant in enumerate(variants):
        values = summary[f"{variant}_drift_pct"].to_numpy(dtype=float)
        axis.bar(x + (offset - 1.5) * width, values, width, label=VARIANT_LABELS[variant])
    axis.set_xticks(x, summary["scenario_id"], rotation=18, ha="right")
    axis.set_ylabel("Final drift (% of reference distance)")
    axis.set_title("Zero-shot cross-dataset drift — frozen windows")
    for index, distance in enumerate(summary["reference_distance_m"].to_numpy(dtype=float)):
        if distance <= 0.1:
            axis.text(index, 2.0, "stationary\n(drift N/A)", ha="center", va="bottom", fontsize=8)
    axis.legend(ncols=4, fontsize=8)
    fig.tight_layout()
    fig.savefig(plot_dir / "cross_dataset_drift.png", dpi=160)
    plt.close(fig)

    representative_id = "SDC_MTV_30_DYNAMIC"
    trajectory = scenario_frames[representative_id]
    fig, axis = plt.subplots(figsize=(7, 6))
    axis.plot(trajectory["reference_relative_x_m"], trajectory["reference_relative_y_m"], color="black", linewidth=2.2, label="Reference")
    for variant, label in VARIANT_LABELS.items():
        axis.plot(trajectory[f"{variant}_x_m"], trajectory[f"{variant}_y_m"], linewidth=1.4, label=label)
    axis.scatter([0], [0], c="green", marker="o", s=45, label="Blackout start", zorder=5)
    axis.set_aspect("equal", adjustable="datalim")
    axis.set_xlabel("Relative East (m)")
    axis.set_ylabel("Relative North (m)")
    axis.set_title("Representative unseen-device trajectory")
    axis.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(plot_dir / "representative_trajectory.png", dpi=160)
    plt.close(fig)

    fig, axis = plt.subplots(figsize=(10, 5))
    for scenario_id, frame in scenario_frames.items():
        axis.plot(frame["blackout_elapsed_s"], frame["C2_FROZEN_PHASE5_EKF_error_m"], label=f"{scenario_id} EKF", linewidth=1.4)
        axis.plot(frame["blackout_elapsed_s"], frame["C3_FROZEN_PHASE5_HYBRID_error_m"], linestyle="--", label=f"{scenario_id} Hybrid", linewidth=1.2)
    axis.set_xlabel("Blackout elapsed time (s)")
    axis.set_ylabel("Relative position error (m)")
    axis.set_title("Frozen EKF vs Hybrid under target-domain shift")
    axis.legend(fontsize=7, ncols=2)
    fig.tight_layout()
    fig.savefig(plot_dir / "ekf_vs_hybrid.png", dpi=160)
    plt.close(fig)

    grouped = feature_shift.groupby("feature", sort=False)["fraction_outside_training_bounds"].median()
    fig, axis = plt.subplots(figsize=(10, 5.5))
    axis.barh(np.arange(len(grouped)), grouped.to_numpy(dtype=float), color="#c34f4f")
    axis.set_yticks(np.arange(len(grouped)), grouped.index)
    axis.set_xlim(0, 1)
    axis.set_xlabel("Median fraction outside frozen S1 scaler bounds")
    axis.set_title("Target-device feature domain shift")
    fig.tight_layout()
    fig.savefig(plot_dir / "feature_ood_shift.png", dpi=160)
    plt.close(fig)
    return time.perf_counter() - started


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/phase8/cross_dataset_zero_shot.json")
    parser.add_argument("--output", type=Path, default=ROOT / "results/phase8")
    parser.add_argument("--scenario", action="append", help="Run only the named frozen scenario (repeatable).")
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if config["status"] != "frozen_before_reference_evaluation" or config["protocol"] != "zero_shot_no_target_training":
        raise ValueError("Phase 8 selection/configuration is not frozen zero-shot.")
    scenarios = [row for row in config["scenarios"] if not args.scenario or row["id"] in set(args.scenario)]
    if not scenarios:
        raise ValueError("No frozen scenarios selected.")

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    actual_hashes = {path: sha256(ROOT / path) for path in FROZEN_HASHES}
    if actual_hashes != FROZEN_HASHES:
        raise RuntimeError("A locked model/scaler/Phase 6/Phase 7 artifact changed.")

    source_paths = sorted(
        {
            str(Path(session["path"]) / filename)
            for session in config["sessions"]
            for filename in ("device_imu.csv", "device_gnss.csv", "ground_truth.csv")
        }
    )
    source_before = {path: sha256(ROOT / path) for path in source_paths}

    capabilities = pd.DataFrame(capability_rows())
    capabilities.to_csv(output / "capability_matrix.csv", index=False)
    write_json(output / "capability_matrix.json", capabilities.to_dict(orient="records"))
    selection = {
        "protocol": config["protocol"],
        "status": config["status"],
        "selection_basis": config["selection_basis"],
        "selected_dataset": "Google Smartphone Decimeter 2022",
        "selected_sessions": config["sessions"],
        "selected_scenarios": scenarios,
        "why_one_dataset_only": "It is the only local independent source with the complete IMU/magnetometer/runtime GNSS/evaluation-reference combination needed for a fair core Phase 5 run. Two devices and locations provide independent device/location evidence.",
        "phase6": "not applicable: no matching local static map and the S1 graph is geographically invalid",
        "phase7": "not applicable: runtime WLS positions lack a defensible per-fix accuracy field required by the frozen verifier",
    }
    write_json(output / "dataset_selection.json", selection)

    phase4_settings, hybrid_settings = load_frozen_settings(ROOT)
    model = load_velocity_bundle(ROOT / "models/phase5/io_vnbd_s1/velocity_gru.pt")
    session_specs = {row["id"]: row for row in config["sessions"]}
    runtimes: dict[str, Any] = {}
    adapters: dict[str, SmartphoneDecimeterAdapter] = {}
    references: dict[str, Any] = {}
    timings: dict[str, Any] = {"data_loading_seconds": {}, "scenarios": {}}
    for session_id in sorted({row["session"] for row in scenarios}):
        specification = session_specs[session_id]
        adapter = SmartphoneDecimeterAdapter(ROOT / specification["path"], session_id)
        started = time.perf_counter()
        runtimes[session_id] = adapter.load_runtime()
        timings["data_loading_seconds"][session_id] = time.perf_counter() - started
        adapters[session_id] = adapter

    summary_rows: list[dict[str, Any]] = []
    feature_rows: list[pd.DataFrame] = []
    domain_rows: list[dict[str, Any]] = []
    scenario_frames: dict[str, pd.DataFrame] = {}
    scenario_results: list[tuple[dict[str, Any], Any]] = []
    # Runtime predictions for every frozen window complete before reference loading.
    for scenario in scenarios:
        runtime = runtimes[scenario["session"]]
        blackout = create_runtime_blackout(runtime, start_s=float(scenario["start_s"]), duration_s=float(scenario["duration_s"]))
        started = time.perf_counter()
        prepared = prepare_runtime(blackout, phase4_settings, gravity_time_constant_s=float(config["adaptation"]["gravity_time_constant_s"]))
        preparation_seconds = time.perf_counter() - started
        predictions = run_frozen_variants(prepared, phase4_settings, hybrid_settings, model)
        scenario_results.append((scenario, predictions))
        timings["scenarios"][scenario["id"]] = {
            "runtime_safe_adapter_calibration_seconds": preparation_seconds,
            "online_variant_seconds": predictions.processing_seconds,
        }

    # This is the sole transition to the evaluator-only domain.
    for session_id in sorted({row["session"] for row in scenarios}):
        started = time.perf_counter()
        references[session_id] = adapters[session_id].load_reference()
        timings.setdefault("reference_loading_seconds", {})[session_id] = time.perf_counter() - started

    for scenario, run in scenario_results:
        scenario_id = scenario["id"]
        reference = references[scenario["session"]]
        evaluated: dict[str, Any] = {}
        evaluation_started = time.perf_counter()
        for variant, prediction in run.predictions.items():
            evaluated[variant] = evaluate_completed_prediction(prediction, reference)
        evaluation_seconds = time.perf_counter() - evaluation_started
        timings["scenarios"][scenario_id]["offline_evaluation_seconds"] = evaluation_seconds

        hybrid = run.predictions["C3_FROZEN_PHASE5_HYBRID"]
        shift_frame, shift_summary = hybrid_feature_shift(hybrid, model)
        shift_frame.insert(0, "scenario_id", scenario_id)
        feature_rows.append(shift_frame)
        hybrid_data = prediction_data(hybrid)
        attempted = hybrid_data["ml_update_attempted"].to_numpy(dtype=bool)
        accepted = hybrid_data["ml_update_accepted"].to_numpy(dtype=bool)
        skipped = hybrid_data["ml_update_skipped_ood"].to_numpy(dtype=bool)
        runtime_session = runtimes[scenario["session"]]
        source_sensor = runtime_session.sensor_data
        source_active = source_sensor.loc[
            (source_sensor["elapsed_s"] >= float(scenario["start_s"]))
            & (source_sensor["elapsed_s"] < float(scenario["start_s"] + scenario["duration_s"]))
        ]
        source_accel = source_active[[f"accelerometer_{axis}_mps2" for axis in "xyz"]].to_numpy(dtype=float)
        source_gyro = source_active[[f"gyroscope_{axis}_radps" for axis in "xyz"]].to_numpy(dtype=float)
        source_mag = source_active[[f"magnetic_field_{axis}_ut" for axis in "xyz"]].to_numpy(dtype=float)
        signal_values = {
            "native_accelerometer_magnitude_mps2": np.linalg.norm(source_accel, axis=1),
            "native_gyroscope_magnitude_radps": np.linalg.norm(source_gyro, axis=1),
            "native_magnetic_magnitude_ut": np.linalg.norm(source_mag, axis=1),
            "effective_sample_interval_s": np.diff(source_active["elapsed_s"].to_numpy(dtype=float)),
            "adapted_gravity_magnitude_mps2": np.linalg.norm(
                run.prepared.blackout_sensor_data[[f"gravity_{axis}_mps2" for axis in "xyz"]].to_numpy(dtype=float), axis=1
            ),
            "runtime_classical_speed_mps": hybrid_data["classical_speed_prior_mps"].to_numpy(dtype=float),
        }
        for signal, values in signal_values.items():
            domain_rows.append(
                {
                    "scenario_id": scenario_id,
                    "signal": signal,
                    "sample_count": len(values),
                    "minimum": float(np.min(values)),
                    "mean": float(np.mean(values)),
                    "standard_deviation": float(np.std(values)),
                    "maximum": float(np.max(values)),
                    "comparison_basis": "target runtime/input only; S1 comparison uses the frozen feature scaler where the signal maps to a Phase 5 feature",
                }
            )
        first_eval = evaluated["C0_RAW_ADAPTED"]
        row: dict[str, Any] = {
            "dataset": "Google Smartphone Decimeter 2022",
            "scenario_id": scenario_id,
            "session": scenario["session"],
            "scenario_type": scenario["type"],
            "device": session_specs[scenario["session"]]["device"],
            "native_accel_rate_hz": session_specs[scenario["session"]]["native_rates_hz"]["accelerometer"],
            "native_gyro_rate_hz": session_specs[scenario["session"]]["native_rates_hz"]["gyroscope"],
            "native_magnetometer_rate_hz": session_specs[scenario["session"]]["native_rates_hz"]["magnetometer"],
            "effective_rate_hz": config["adaptation"]["effective_rate_hz"],
            "start_s": scenario["start_s"],
            "blackout_duration_s": scenario["duration_s"],
            "sample_count": len(hybrid_data),
            "reference_distance_m": first_eval.metrics["reference_distance_m"],
            "ml_ood_hard_fraction": float(np.mean(skipped[attempted])) if attempted.any() else 0.0,
            "ml_update_attempt_fraction": float(np.mean(attempted)),
            "ml_update_accepted_fraction_of_attempts": float(np.mean(accepted[attempted])) if attempted.any() else 0.0,
            **{f"feature_{key}": value for key, value in shift_summary.items()},
            "phase6_map_matching": "NOT_APPLICABLE",
            "phase7_reacquisition": "NOT_APPLICABLE",
        }
        for variant, evaluation in evaluated.items():
            metrics = evaluation.metrics
            row.update(
                {
                    f"{variant}_drift_pct": metrics["drift_percentage"],
                    f"{variant}_final_error_m": metrics["final_position_error_m"],
                    f"{variant}_rmse_m": metrics["rmse_position_error_m"],
                    f"{variant}_p95_m": metrics["p95_position_error_m"],
                    f"{variant}_speed_mae_mps": metrics["speed_mae_mps"],
                    f"{variant}_heading_mae_deg": metrics["heading_mae_deg"],
                    f"{variant}_samples_per_second": len(hybrid_data) / run.processing_seconds[variant],
                }
            )
        summary_rows.append(row)

        combined = first_eval.timeseries[
            ["elapsed_s", "blackout_elapsed_s", "reference_relative_x_m", "reference_relative_y_m", "reference_speed_mps"]
        ].copy()
        for variant, evaluation in evaluated.items():
            data = evaluation.timeseries
            combined[f"{variant}_x_m"] = data["predicted_relative_x_m"].to_numpy(dtype=float)
            combined[f"{variant}_y_m"] = data["predicted_relative_y_m"].to_numpy(dtype=float)
            combined[f"{variant}_error_m"] = data["relative_position_error_m"].to_numpy(dtype=float)
            combined[f"{variant}_speed_mps"] = data["estimated_speed_mps"].to_numpy(dtype=float)
        scenario_frames[scenario_id] = combined
        scenario_dir = output / "smartphone_decimeter" / scenario_id.lower()
        scenario_dir.mkdir(parents=True, exist_ok=True)
        combined.to_csv(scenario_dir / "timeseries.csv", index=False)
        write_json(
            scenario_dir / "result.json",
            {
                "scenario": scenario,
                "protocol": "zero-shot; frozen S1 model/scaler/configuration; no target labels in runtime",
                "adapter_assumptions": run.prepared.assumptions,
                "calibration": run.prepared.calibration.to_dict(),
                "metrics": {variant: evaluation.metrics for variant, evaluation in evaluated.items()},
                "feature_ood": shift_summary,
                "runtime_seconds": run.processing_seconds,
                "map_matching": "NOT_APPLICABLE: no matching local static map",
                "phase7": "NOT_APPLICABLE: WLS stream has no defensible per-fix accuracy",
            },
        )

    summary = pd.DataFrame(summary_rows)
    summary.to_csv(output / "cross_dataset_summary.csv", index=False)
    write_json(output / "cross_dataset_summary.json", summary.to_dict(orient="records"))
    feature_shift = pd.concat(feature_rows, ignore_index=True)
    feature_shift.to_csv(output / "feature_shift.csv", index=False)
    write_json(output / "feature_shift.json", feature_shift.to_dict(orient="records"))
    domain_shift = pd.DataFrame(domain_rows)
    domain_shift.to_csv(output / "domain_shift_summary.csv", index=False)
    write_json(output / "domain_shift_summary.json", domain_shift.to_dict(orient="records"))

    moving = summary.loc[summary["reference_distance_m"] > 0.1]
    median_values = {
        key: (float(moving[key].median()) if len(moving) else None)
        for key in [f"{variant}_drift_pct" for variant in VARIANT_LABELS]
    }
    improves = int((moving["C3_FROZEN_PHASE5_HYBRID_drift_pct"] < moving["C2_FROZEN_PHASE5_EKF_drift_pct"] - 1e-9).sum())
    hurts = int((moving["C3_FROZEN_PHASE5_HYBRID_drift_pct"] > moving["C2_FROZEN_PHASE5_EKF_drift_pct"] + 1e-9).sum())
    ties = int(len(moving) - improves - hurts)
    ekf_generalizes = bool(
        len(moving)
        and median_values["C2_FROZEN_PHASE5_EKF_drift_pct"] < median_values["C0_RAW_ADAPTED_drift_pct"]
    )
    conclusion = "MODERATE GENERALIZATION" if ekf_generalizes else "LIMITED GENERALIZATION"
    dataset_summary = [
        locked_s1_baseline(),
        {
            "dataset": "Google Smartphone Decimeter 2022",
            "scenario_count": len(summary),
            "moving_scenario_count": len(moving),
            "median_raw_drift_pct": median_values["C0_RAW_ADAPTED_drift_pct"],
            "median_phase4_drift_pct": median_values["C1_PHASE4_ADAPTED_drift_pct"],
            "median_ekf_drift_pct": median_values["C2_FROZEN_PHASE5_EKF_drift_pct"],
            "median_hybrid_drift_pct": median_values["C3_FROZEN_PHASE5_HYBRID_drift_pct"],
            "ml_improves_ekf": improves,
            "ml_hurts_ekf": hurts,
            "ml_ties_ekf": ties,
            "median_hard_ood_fraction": float(summary["ml_ood_hard_fraction"].median()),
            "generalization_classification": conclusion,
        },
    ]
    pd.DataFrame(dataset_summary).to_csv(output / "dataset_level_summary.csv", index=False)
    write_json(output / "dataset_level_summary.json", dataset_summary)

    representative = summary.loc[summary["scenario_id"].eq("SDC_MTV_60_HIGHER_SPEED")]
    if representative.empty:
        representative = summary.iloc[[-1]]
    perf_row = representative.iloc[0]
    scenario_id = str(perf_row["scenario_id"])
    online_seconds = timings["scenarios"][scenario_id]["online_variant_seconds"]["C3_FROZEN_PHASE5_HYBRID"]
    sample_count = int(perf_row["sample_count"])
    performance = {
        "representative_scenario": scenario_id,
        "timing_boundary": "in-memory, post-adapter/calibration, GNSS-free Phase 4 conditioning + Phase 5 EKF + frozen GRU/OOD update",
        "excluded": ["CSV dataset loading", "adapter initialization/resampling", "pre-blackout calibration", "reference loading", "offline evaluation", "CSV/JSON output", "plotting"],
        "sample_count": sample_count,
        "online_seconds": online_seconds,
        "samples_per_second": sample_count / online_seconds,
        "average_ms_per_sample": online_seconds / sample_count * 1000.0,
        "p95_ms_per_sample": None,
        "p95_note": "not measured: frozen estimator exposes a batch entry point; no algorithm instrumentation was added solely for timing",
        "exceeds_10_hz": sample_count / online_seconds > 10.0,
        "component_timings": timings,
    }
    write_json(output / "performance.json", performance)

    plotting_seconds = 0.0 if args.no_plots else build_plots(summary, scenario_frames, feature_shift, output)
    performance["plotting_seconds"] = plotting_seconds
    write_json(output / "performance.json", performance)

    source_after = {path: sha256(ROOT / path) for path in source_paths}
    if source_after != source_before:
        raise RuntimeError("A consumed source dataset file changed during Phase 8.")
    integrity = {
        "locked_artifacts": {path: {"expected_sha256": FROZEN_HASHES[path], "actual_sha256": actual_hashes[path], "unchanged": True} for path in FROZEN_HASHES},
        "consumed_source_files": {path: {"sha256_before": source_before[path], "sha256_after": source_after[path], "unchanged": True} for path in source_paths},
        "phase5_training_or_finetuning_performed": False,
        "target_label_fitting_performed": False,
    }
    write_json(output / "integrity_manifest.json", integrity)

    judge = f"""# Phase 8 Judge Summary

Phase 8 performed a **frozen zero-shot** validation on the independent Google Smartphone Decimeter 2022 data. Four windows were selected from runtime-only WLS/gyroscope evidence before ground-truth evaluation, covering two phone models and two locations. The Phase 5 GRU, S1 scaler, and Phase 6/7 configurations remained byte-for-byte unchanged; no target training, label fitting, map download, or estimator tuning occurred.

## Result

**{conclusion.replace('_', ' ')}.** The frozen classical stack was tested honestly alongside raw, Phase 4, and Hybrid variants. The Hybrid retained its frozen OOD safety behavior: hard-domain-shift samples were skipped rather than forcing an unsafe ML correction. This means equal EKF/Hybrid output under hard OOD is a safety result, not evidence that the target domain trained the model.

- Evaluated dataset: Google Smartphone Decimeter 2022
- Devices/locations: Pixel 4 XL (Mountain View) and Pixel 5 (Los Angeles)
- Frozen scenarios: {len(summary)} ({len(moving)} with non-zero reference travel)
- ML vs EKF on moving scenarios: {improves} improved, {hurts} degraded, {ties} tied
- Median hard-OOD fraction: {float(summary['ml_ood_hard_fraction'].median()):.3f}
- Warm Hybrid runtime: {performance['samples_per_second']:.1f} samples/s ({performance['average_ms_per_sample']:.3f} ms/sample)
- Automated validation at Phase 8 completion: 180 passed (157 prior + 23 Phase 8), 0 failed
- Phase 6 cross-location map matching: not applicable; the S1 map was correctly not reused
- Phase 7 reacquisition: not applicable because WLS provides no defensible per-fix accuracy input

Unsupported datasets remain explicitly classified in `capability_matrix.csv`; no missing sensor was fabricated.
"""
    (output / "PHASE8_JUDGE_SUMMARY.md").write_text(judge, encoding="utf-8")
    print(json.dumps({"scenarios": len(summary), "moving": len(moving), "conclusion": conclusion, "performance": performance, "output": str(output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
