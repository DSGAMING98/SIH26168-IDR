#!/usr/bin/env python3
"""Train and freeze the Phase 5 compact velocity-residual GRU."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
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
import torch  # noqa: E402

from idr.calibrated_dr import Phase4Settings  # noqa: E402
from idr.hybrid.hybrid_idr import HybridSettings  # noqa: E402
from idr.io_vnbd import load_journey, sha256_file  # noqa: E402
from idr.ml.features import FEATURE_ORDER, make_causal_windows, verify_split_manifest  # noqa: E402
from idr.ml.velocity_model import (  # noqa: E402
    VelocityModelBundle,
    VelocityModelConfig,
    fit_feature_scaler,
    save_velocity_bundle,
    train_velocity_model,
)
from idr.phase5_data import DevelopmentSequence, build_development_sequence  # noqa: E402


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


def _speed_metrics(predicted: np.ndarray, reference: np.ndarray) -> dict[str, float]:
    error = np.asarray(predicted, dtype=float) - np.asarray(reference, dtype=float)
    correlation = (
        float(np.corrcoef(predicted, reference)[0, 1])
        if np.std(predicted) > 1e-12 and np.std(reference) > 1e-12
        else 0.0
    )
    return {
        "mae_mps": float(np.mean(np.abs(error))),
        "rmse_mps": float(np.sqrt(np.mean(np.square(error)))),
        "p95_absolute_error_mps": float(np.percentile(np.abs(error), 95)),
        "mean_signed_error_mps": float(np.mean(error)),
        "correlation": correlation,
    }


def _window_sequences(
    sequences: list[DevelopmentSequence],
    scaler: Any,
    window_steps: int,
    stride_steps: int,
) -> tuple[np.ndarray, np.ndarray, pd.DataFrame]:
    inputs: list[np.ndarray] = []
    targets: list[np.ndarray] = []
    trace_rows: list[dict[str, Any]] = []
    for sequence in sequences:
        normalized = scaler.transform(sequence.features.to_numpy(dtype=np.float32))
        windows = make_causal_windows(
            normalized,
            sequence.target_residual_mps,
            window_steps=window_steps,
            stride_steps=stride_steps,
        )
        inputs.append(windows.inputs)
        assert windows.targets is not None
        targets.append(windows.targets)
        for end_index in windows.end_indices:
            trace_rows.append(
                {
                    "interval_id": sequence.interval_id,
                    "elapsed_s": float(sequence.elapsed_s[end_index]),
                    "classical_speed_mps": float(sequence.classical_speed_mps[end_index]),
                    "reference_speed_mps": float(sequence.reference_speed_mps[end_index]),
                }
            )
    return np.concatenate(inputs), np.concatenate(targets), pd.DataFrame(trace_rows)


def _development_subintervals(
    blocks: list[dict[str, Any]], duration_s: float, minimum_duration_s: float
) -> list[dict[str, Any]]:
    """Create realistic independent outages without crossing split blocks."""

    result: list[dict[str, Any]] = []
    for block in blocks:
        cursor = float(block["start_s"])
        block_end = float(block["end_s"])
        sequence_number = 1
        while block_end - cursor >= minimum_duration_s:
            end = min(cursor + duration_s, block_end)
            result.append(
                {
                    "id": f"{block['id']}_OUTAGE_{sequence_number:02d}",
                    "start_s": cursor,
                    "end_s": end,
                    "parent_block": block["id"],
                }
            )
            cursor = end
            sequence_number += 1
    return result


def _plot_training(history: pd.DataFrame, path: Path) -> None:
    figure, axis = plt.subplots(figsize=(8.8, 4.8))
    axis.plot(history["epoch"], history["training_loss"], label="Training Huber loss", color="#0072B2")
    axis.plot(history["epoch"], history["validation_loss"], label="Validation Huber loss", color="#D55E00")
    axis.set(title="Phase 5 GRU training curve", xlabel="Epoch", ylabel="Huber loss")
    axis.grid(True, alpha=0.25)
    axis.legend(frameon=False)
    figure.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def _plot_validation(trace: pd.DataFrame, path: Path) -> None:
    figure, axes = plt.subplots(len(trace["interval_id"].unique()), 1, figsize=(10, 8), sharey=True)
    axes = np.atleast_1d(axes)
    for axis, (interval_id, group) in zip(axes, trace.groupby("interval_id", sort=False)):
        relative = group["elapsed_s"] - group["elapsed_s"].iloc[0]
        axis.plot(relative, group["reference_speed_mps"], color="#222222", label="VBOX label - validation only")
        axis.plot(relative, group["classical_speed_mps"], color="#E69F00", label="Classical EKF")
        axis.plot(relative, group["ml_corrected_speed_mps"], color="#009E73", label="ML-corrected")
        axis.set_ylabel("m/s")
        axis.set_title(interval_id, loc="left", fontsize=9)
        axis.grid(True, alpha=0.22)
    axes[-1].set_xlabel("Time inside validation block (s)")
    axes[0].legend(frameon=False, ncol=3, fontsize=8)
    figure.suptitle("Non-benchmark validation speed", x=0.12, ha="left", weight="bold")
    figure.tight_layout()
    figure.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/phase5/io_vnbd_s1_ml.json"))
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    config_path = _resolve(args.config)
    config = _json(config_path)
    split_path = _resolve(config["split_config"])
    phase4_path = _resolve(config["phase4_config"])
    ekf_path = ROOT / "configs" / "phase5" / "io_vnbd_s1_ekf.json"
    split = _json(split_path)
    split_checks = verify_split_manifest(split)
    phase4_settings = Phase4Settings.from_dict(_json(phase4_path))
    hybrid_settings = HybridSettings.from_dict(_json(ekf_path))
    model_config = VelocityModelConfig.from_dict(config)
    journey = load_journey(str(config["session"]), project_root_path=ROOT)

    development_duration = float(config["training"]["development_blackout_duration_s"])
    minimum_development_duration = float(
        config["training"]["minimum_development_blackout_duration_s"]
    )
    training_subintervals = _development_subintervals(
        split["training_intervals"], development_duration, minimum_development_duration
    )
    validation_subintervals = _development_subintervals(
        split["validation_intervals"], development_duration, minimum_development_duration
    )
    training_sequences = [
        build_development_sequence(journey, interval, phase4_settings, hybrid_settings)
        for interval in training_subintervals
    ]
    validation_sequences = [
        build_development_sequence(journey, interval, phase4_settings, hybrid_settings)
        for interval in validation_subintervals
    ]
    scaler = fit_feature_scaler(sequence.features for sequence in training_sequences)
    stride = int(config["training"]["window_stride_steps"])
    train_x, train_y, train_trace = _window_sequences(
        training_sequences, scaler, model_config.window_steps, stride
    )
    validation_x, validation_y, validation_trace = _window_sequences(
        validation_sequences, scaler, model_config.window_steps, stride
    )
    result = train_velocity_model(
        train_x,
        train_y,
        validation_x,
        validation_y,
        model_config,
        config["training"],
    )
    result.model.eval()
    with torch.inference_mode():
        predicted_residual = result.model(torch.from_numpy(validation_x)).numpy()
    classical = validation_trace["classical_speed_mps"].to_numpy(dtype=float)
    reference = validation_trace["reference_speed_mps"].to_numpy(dtype=float)
    corrected = np.maximum(0.0, classical + predicted_residual)
    validation_trace["target_residual_mps"] = validation_y
    validation_trace["predicted_residual_mps"] = predicted_residual
    validation_trace["ml_corrected_speed_mps"] = corrected
    classical_metrics = _speed_metrics(classical, reference)
    corrected_metrics = _speed_metrics(corrected, reference)
    corrected_error = corrected - reference
    residual_variance = float(np.var(corrected_error, ddof=1))
    parameter_count = int(sum(parameter.numel() for parameter in result.model.parameters()))
    validation_metrics: dict[str, Any] = {
        "classical_speed": classical_metrics,
        "ml_corrected_speed": corrected_metrics,
        "ml_measurement_residual_variance_mps2": residual_variance,
        "best_validation_huber_loss": float(result.history[result.best_epoch - 1]["validation_loss"]),
    }

    checkpoint_path = _resolve(config["checkpoint_path"])
    save_velocity_bundle(
        checkpoint_path,
        result.model,
        scaler,
        model_config,
        residual_variance,
        validation_metrics,
    )
    model_dir = checkpoint_path.parent
    result_dir = ROOT / "results" / "phase5" / "io_vnbd" / "s1"
    training_dir = result_dir / "training"
    plots_dir = result_dir / "plots"
    for directory in (model_dir, training_dir, plots_dir):
        directory.mkdir(parents=True, exist_ok=True)
    history = pd.DataFrame(result.history)
    history.to_csv(training_dir / "training_history.csv", index=False)
    (training_dir / "training_history.json").write_text(
        json.dumps(result.history, indent=2) + "\n", encoding="utf-8"
    )
    validation_trace.to_csv(training_dir / "validation_predictions.csv", index=False)
    (training_dir / "validation_metrics.json").write_text(
        json.dumps(validation_metrics, indent=2) + "\n", encoding="utf-8"
    )
    scaler_payload = scaler.to_dict()
    (model_dir / "feature_scaler.json").write_text(
        json.dumps(scaler_payload, indent=2) + "\n", encoding="utf-8"
    )
    model_metadata = {
        **model_config.to_dict(),
        "architecture": config["model"]["architecture"],
        "parameter_count": parameter_count,
        "checkpoint_selected_by": "minimum validation Huber loss only",
        "best_epoch": result.best_epoch,
        "validation_metrics": validation_metrics,
        "feature_order": list(FEATURE_ORDER),
        "prediction_target": config["prediction_target"],
        "training_windows": int(len(train_x)),
        "validation_windows": int(len(validation_x)),
        "training_seconds": result.training_seconds,
    }
    (model_dir / "model_config.json").write_text(
        json.dumps(model_metadata, indent=2) + "\n", encoding="utf-8"
    )
    split_manifest = {
        **split,
        "validation_checks": split_checks,
        "training_feature_rows": int(sum(len(sequence.features) for sequence in training_sequences)),
        "validation_feature_rows": int(sum(len(sequence.features) for sequence in validation_sequences)),
        "training_windows": int(len(train_x)),
        "validation_windows": int(len(validation_x)),
        "development_blackout_duration_s": development_duration,
        "training_development_sequences": training_subintervals,
        "validation_development_sequences": validation_subintervals,
        "feature_scaler_fit_rows": int(sum(len(sequence.features) for sequence in training_sequences)),
        "window_steps": model_config.window_steps,
        "window_stride_steps": stride,
    }
    (result_dir / "split_manifest.json").write_text(
        json.dumps(split_manifest, indent=2) + "\n", encoding="utf-8"
    )
    _plot_training(history, plots_dir / "training_curve.png")
    _plot_validation(validation_trace, plots_dir / "speed_validation.png")
    model_card = f"""# Phase 5 Velocity GRU

## What it predicts

A bounded correction to the causal classical EKF forward-speed estimate. It never predicts latitude, longitude, or a trajectory.

## Runtime sensor inputs

The fixed 2-second history contains: {', '.join(FEATURE_ORDER)}. Every feature is derived from GNSS-free phone sensors or the causal EKF state.

## Training and exclusions

The model used IO-VNBD S1 time-blocked development intervals. VBOX speed was used offline only as the target label. All five benchmark intervals and the preselected surprise holdout were quarantined with 120 seconds before blackout start and 60 seconds after blackout end. Scaling used training rows only; checkpoint selection used validation loss only.

## Size and limitations

The one-layer {model_config.hidden_size}-unit GRU has {parameter_count:,} parameters. It was trained on one journey and is not evidence of cross-device or cross-dataset generalization. OOD feature exceedance reduces or removes its EKF influence.

## Android deployment plan

The graph uses a standard GRU, tanh, and linear head, suitable for later export through PyTorch/ONNX to a mobile runtime. Phase 5 does not build that export or an Android application.
"""
    (model_dir / "model_card.md").write_text(model_card, encoding="utf-8")
    frozen = {
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "development_protocol": "train -> validation checkpoint selection -> freeze -> benchmark",
        "python": sys.version,
        "platform": platform.platform(),
        "torch_version": torch.__version__,
        "config_sha256": {
            "ml": _sha256(config_path),
            "split": _sha256(split_path),
            "phase4": _sha256(phase4_path),
            "ekf": _sha256(ekf_path),
        },
        "checkpoint_sha256": _sha256(checkpoint_path),
        "checkpoint_path": str(checkpoint_path.relative_to(ROOT)).replace("\\", "/"),
        "source_sha256": {
            "smartphone": sha256_file(journey.smartphone_path),
            "vbox_reference": sha256_file(journey.vehicle_path),
        },
        "parameter_count": parameter_count,
        "checkpoint_size_bytes": checkpoint_path.stat().st_size,
        "best_epoch": result.best_epoch,
        "training_seconds": result.training_seconds,
        "training_windows": int(len(train_x)),
        "validation_windows": int(len(validation_x)),
        "validation_metrics": validation_metrics,
    }
    (result_dir / "frozen_configuration.json").write_text(
        json.dumps(frozen, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(frozen, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
