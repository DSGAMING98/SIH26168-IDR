"""Causal runtime feature and compact velocity-model utilities."""

from .features import (
    FEATURE_ORDER,
    CausalWindowBatch,
    build_runtime_feature_frame,
    make_causal_windows,
    verify_split_manifest,
)
from .velocity_model import (
    FeatureScaler,
    VelocityGRU,
    VelocityModelBundle,
    VelocityModelConfig,
    fit_feature_scaler,
    load_velocity_bundle,
    save_velocity_bundle,
    train_velocity_model,
)

__all__ = [
    "FEATURE_ORDER",
    "CausalWindowBatch",
    "build_runtime_feature_frame",
    "make_causal_windows",
    "verify_split_manifest",
    "FeatureScaler",
    "VelocityGRU",
    "VelocityModelBundle",
    "VelocityModelConfig",
    "fit_feature_scaler",
    "load_velocity_bundle",
    "save_velocity_bundle",
    "train_velocity_model",
]
