"""Small deterministic GRU that estimates a bounded forward-speed residual."""

from __future__ import annotations

import copy
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from .features import FEATURE_ORDER


@dataclass(frozen=True)
class VelocityModelConfig:
    input_size: int
    hidden_size: int
    num_layers: int
    maximum_residual_mps: float
    window_steps: int
    sample_rate_hz: float
    update_stride_steps: int
    seed: int

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "VelocityModelConfig":
        model = values["model"]
        window = values["causal_window"]
        return cls(
            input_size=len(FEATURE_ORDER),
            hidden_size=int(model["hidden_size"]),
            num_layers=int(model["num_layers"]),
            maximum_residual_mps=float(model["maximum_residual_mps"]),
            window_steps=int(window["steps"]),
            sample_rate_hz=float(window["nominal_sample_rate_hz"]),
            update_stride_steps=int(values["inference"]["update_stride_steps"]),
            seed=int(values["training"]["seed"]),
        )

    @property
    def window_duration_s(self) -> float:
        return self.window_steps / self.sample_rate_hz

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FeatureScaler:
    feature_order: tuple[str, ...]
    means: tuple[float, ...]
    standard_deviations: tuple[float, ...]
    normalized_lower_bounds: tuple[float, ...]
    normalized_upper_bounds: tuple[float, ...]
    fitted_on: str = "training rows only"

    def transform(self, values: np.ndarray) -> np.ndarray:
        array = np.asarray(values, dtype=np.float32)
        if array.shape[-1] != len(self.feature_order):
            raise ValueError("Feature count/order does not match the frozen scaler.")
        return (array - np.asarray(self.means, dtype=np.float32)) / np.asarray(
            self.standard_deviations, dtype=np.float32
        )

    def ood_exceedance(self, normalized_values: np.ndarray) -> float:
        values = np.asarray(normalized_values, dtype=float)
        lower = np.asarray(self.normalized_lower_bounds, dtype=float)
        upper = np.asarray(self.normalized_upper_bounds, dtype=float)
        exceedance = np.maximum(np.maximum(lower - values, values - upper), 0.0)
        return float(np.max(exceedance))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "FeatureScaler":
        return cls(
            feature_order=tuple(values["feature_order"]),
            means=tuple(float(v) for v in values["means"]),
            standard_deviations=tuple(float(v) for v in values["standard_deviations"]),
            normalized_lower_bounds=tuple(float(v) for v in values["normalized_lower_bounds"]),
            normalized_upper_bounds=tuple(float(v) for v in values["normalized_upper_bounds"]),
            fitted_on=str(values.get("fitted_on", "training rows only")),
        )


def fit_feature_scaler(training_frames: Iterable[pd.DataFrame]) -> FeatureScaler:
    arrays = [frame.loc[:, list(FEATURE_ORDER)].to_numpy(dtype=float) for frame in training_frames]
    if not arrays:
        raise ValueError("At least one training feature frame is required.")
    training = np.vstack(arrays)
    if not np.all(np.isfinite(training)):
        raise ValueError("Training features contain NaN or infinity.")
    means = np.mean(training, axis=0)
    standard_deviations = np.std(training, axis=0)
    standard_deviations = np.where(standard_deviations < 1e-6, 1.0, standard_deviations)
    normalized = (training - means) / standard_deviations
    lower = np.percentile(normalized, 0.5, axis=0)
    upper = np.percentile(normalized, 99.5, axis=0)
    return FeatureScaler(
        FEATURE_ORDER,
        tuple(float(v) for v in means),
        tuple(float(v) for v in standard_deviations),
        tuple(float(v) for v in lower),
        tuple(float(v) for v in upper),
    )


class VelocityGRU(nn.Module):
    """One recurrent layer plus one linear head; output is a bounded residual."""

    def __init__(self, config: VelocityModelConfig) -> None:
        super().__init__()
        self.config = config
        self.gru = nn.GRU(
            config.input_size,
            config.hidden_size,
            num_layers=config.num_layers,
            batch_first=True,
        )
        self.output = nn.Linear(config.hidden_size, 1)

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        sequence, _ = self.gru(inputs)
        raw = self.output(sequence[:, -1, :]).squeeze(-1)
        return self.config.maximum_residual_mps * torch.tanh(raw)


@dataclass(frozen=True)
class VelocityModelBundle:
    model: VelocityGRU
    scaler: FeatureScaler
    config: VelocityModelConfig
    validation_residual_variance_mps2: float
    validation_metrics: dict[str, Any]

    def predict_window(self, feature_window: np.ndarray) -> tuple[float, float]:
        values = np.asarray(feature_window, dtype=np.float32)
        expected = (self.config.window_steps, self.config.input_size)
        if values.shape != expected:
            raise ValueError(f"ML window must have shape {expected}.")
        normalized = self.scaler.transform(values)
        self.model.eval()
        with torch.inference_mode():
            tensor = torch.from_numpy(normalized[None, ...])
            residual = float(self.model(tensor).item())
        if not np.isfinite(residual):
            raise FloatingPointError("ML speed residual is not finite.")
        return residual, self.scaler.ood_exceedance(normalized)


@dataclass(frozen=True)
class TrainingResult:
    model: VelocityGRU
    history: list[dict[str, float | int]]
    best_epoch: int
    training_seconds: float


def _set_deterministic_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)


def train_velocity_model(
    train_inputs: np.ndarray,
    train_targets: np.ndarray,
    validation_inputs: np.ndarray,
    validation_targets: np.ndarray,
    config: VelocityModelConfig,
    training_settings: dict[str, Any],
) -> TrainingResult:
    """Train once and select the checkpoint using validation loss only."""

    _set_deterministic_seed(config.seed)
    train_x = torch.from_numpy(np.asarray(train_inputs, dtype=np.float32))
    train_y = torch.from_numpy(np.asarray(train_targets, dtype=np.float32))
    validation_x = torch.from_numpy(np.asarray(validation_inputs, dtype=np.float32))
    validation_y = torch.from_numpy(np.asarray(validation_targets, dtype=np.float32))
    if train_x.ndim != 3 or validation_x.ndim != 3 or len(train_x) == 0 or len(validation_x) == 0:
        raise ValueError("Non-empty three-dimensional train and validation windows are required.")
    model = VelocityGRU(config)
    optimizer = torch.optim.Adam(
        model.parameters(),
        lr=float(training_settings["learning_rate"]),
        weight_decay=float(training_settings.get("weight_decay", 0.0)),
    )
    loss_function = nn.HuberLoss(delta=float(training_settings.get("huber_delta", 1.0)))
    generator = torch.Generator().manual_seed(config.seed)
    loader = DataLoader(
        TensorDataset(train_x, train_y),
        batch_size=int(training_settings["batch_size"]),
        shuffle=True,
        generator=generator,
        num_workers=0,
    )
    best_loss = float("inf")
    best_epoch = 0
    best_state: dict[str, torch.Tensor] | None = None
    stale_epochs = 0
    history: list[dict[str, float | int]] = []
    started = time.perf_counter()
    for epoch in range(1, int(training_settings["maximum_epochs"]) + 1):
        model.train()
        total_loss = 0.0
        seen = 0
        for inputs, targets in loader:
            optimizer.zero_grad(set_to_none=True)
            predictions = model(inputs)
            loss = loss_function(predictions, targets)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), float(training_settings.get("gradient_clip", 5.0)))
            optimizer.step()
            total_loss += float(loss.item()) * len(inputs)
            seen += len(inputs)
        model.eval()
        with torch.inference_mode():
            validation_loss = float(loss_function(model(validation_x), validation_y).item())
        training_loss = total_loss / seen
        history.append({"epoch": epoch, "training_loss": training_loss, "validation_loss": validation_loss})
        if validation_loss < best_loss - float(training_settings.get("minimum_delta", 1e-5)):
            best_loss = validation_loss
            best_epoch = epoch
            best_state = copy.deepcopy(model.state_dict())
            stale_epochs = 0
        else:
            stale_epochs += 1
        if stale_epochs >= int(training_settings["early_stopping_patience"]):
            break
    if best_state is None:
        raise RuntimeError("Training failed to produce a validation checkpoint.")
    model.load_state_dict(best_state)
    model.eval()
    return TrainingResult(model, history, best_epoch, time.perf_counter() - started)


def save_velocity_bundle(
    path: Path,
    model: VelocityGRU,
    scaler: FeatureScaler,
    config: VelocityModelConfig,
    validation_residual_variance_mps2: float,
    validation_metrics: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "state_dict": model.state_dict(),
            "model_config": config.to_dict(),
            "feature_scaler": scaler.to_dict(),
            "validation_residual_variance_mps2": float(validation_residual_variance_mps2),
            "validation_metrics": validation_metrics,
        },
        path,
    )


def load_velocity_bundle(path: Path) -> VelocityModelBundle:
    payload = torch.load(path, map_location="cpu", weights_only=True)
    config = VelocityModelConfig(**payload["model_config"])
    scaler = FeatureScaler.from_dict(payload["feature_scaler"])
    if scaler.feature_order != FEATURE_ORDER:
        raise ValueError("Checkpoint feature order does not match runtime code.")
    model = VelocityGRU(config)
    model.load_state_dict(payload["state_dict"])
    model.eval()
    return VelocityModelBundle(
        model,
        scaler,
        config,
        float(payload["validation_residual_variance_mps2"]),
        dict(payload["validation_metrics"]),
    )
