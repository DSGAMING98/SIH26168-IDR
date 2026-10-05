"""Reference-free classical EKF and ML-assisted EKF runtime pipeline."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from ..blackout import GNSS_DERIVED_FIELDS, EvaluationReference
from ..calibrated_dr import (
    REFERENCE_ONLY_FIELDS,
    Phase4Calibration,
    Phase4Settings,
    integrate_calibrated_dead_reckoning,
)
from ..dead_reckoning import RawDRPrediction
from ..evaluation import local_xy_to_geodetic
from ..fusion.ekf import ACCEL_BIAS, EAST, GYRO_BIAS, NORTH, SPEED, YAW, EKFNoiseConfig, VehicleEKF
from ..ml.features import FEATURE_ORDER, build_runtime_feature_frame
from ..ml.velocity_model import VelocityModelBundle
from ..raw_dr_evaluation import RawDREvaluation, evaluate_raw_dr_prediction


PHASE5_EKF_ALGORITHM = "phase5_classical_ekf_v1"
PHASE5_HYBRID_ALGORITHM = "phase5_hybrid_ekf_gru_v1"


@dataclass(frozen=True)
class HybridSettings:
    noise: EKFNoiseConfig
    initial_position_sigma_floor_m: float
    initial_speed_sigma_mps: float
    initial_yaw_sigma_deg: float
    initial_accel_bias_sigma_mps2: float
    initial_gyro_bias_sigma_radps: float
    enable_stationary_updates: bool
    enable_heading_updates: bool
    ood_soft_exceedance: float
    ood_hard_exceedance: float
    ood_variance_inflation: float
    minimum_ml_variance_mps2: float
    max_allowed_dt_s: float
    independent_classical_prior: bool = False
    turning_velocity_constraint: bool = False

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "HybridSettings":
        initial = values["initial_covariance"]
        updates = values["runtime_updates"]
        ood = values["ood_safety"]
        return cls(
            noise=EKFNoiseConfig.from_dict(values),
            initial_position_sigma_floor_m=float(initial["position_sigma_floor_m"]),
            initial_speed_sigma_mps=float(initial["speed_sigma_mps"]),
            initial_yaw_sigma_deg=float(initial["yaw_sigma_deg"]),
            initial_accel_bias_sigma_mps2=float(initial["accel_bias_sigma_mps2"]),
            initial_gyro_bias_sigma_radps=float(initial["gyro_bias_sigma_radps"]),
            enable_stationary_updates=bool(updates["stationary_updates"]),
            enable_heading_updates=bool(updates["gated_heading_updates"]),
            ood_soft_exceedance=float(ood["soft_exceedance"]),
            ood_hard_exceedance=float(ood["hard_exceedance"]),
            ood_variance_inflation=float(ood["variance_inflation"]),
            minimum_ml_variance_mps2=float(updates["minimum_ml_variance_mps2"]),
            max_allowed_dt_s=float(values["maximum_dt_s"]),
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["noise"] = self.noise.to_dict()
        return result


@dataclass(frozen=True)
class HybridPrediction:
    data: pd.DataFrame
    feature_data: pd.DataFrame
    calibration: Phase4Calibration
    mode: str
    algorithm: str
    coordinate_frame: str = "local ENU: x East, y North; yaw clockwise from North"


@dataclass(frozen=True)
class HybridEvaluation:
    metrics: dict[str, Any]
    timeseries: pd.DataFrame


def _initial_ekf(
    calibration: Phase4Calibration,
    settings: HybridSettings,
    phone_gnss_accuracy_m: float | None,
) -> VehicleEKF:
    accuracy = (
        settings.initial_position_sigma_floor_m
        if phone_gnss_accuracy_m is None or not np.isfinite(phone_gnss_accuracy_m)
        else max(settings.initial_position_sigma_floor_m, float(phone_gnss_accuracy_m))
    )
    return VehicleEKF.initialized(
        speed_mps=calibration.initialization.initial_speed_mps,
        yaw_deg=calibration.initial_calibrated_heading_deg,
        # Phase 4 preprocessing has already removed the reliable calibrated
        # biases. EKF bias states therefore estimate only the remaining
        # residual and start at the defensible zero-mean prior.
        accel_bias_mps2=0.0,
        gyro_bias_radps=0.0,
        position_sigma_m=accuracy,
        speed_sigma_mps=settings.initial_speed_sigma_mps,
        yaw_sigma_deg=max(
            settings.initial_yaw_sigma_deg,
            float(calibration.yaw_dispersion_deg or settings.initial_yaw_sigma_deg),
        ),
        accel_bias_sigma_mps2=settings.initial_accel_bias_sigma_mps2,
        gyro_bias_sigma_radps=settings.initial_gyro_bias_sigma_radps,
        noise=settings.noise,
    )


def run_hybrid_estimator(
    blackout_sensor_data: pd.DataFrame,
    calibration: Phase4Calibration,
    phase4_settings: Phase4Settings,
    hybrid_settings: HybridSettings,
    model_bundle: VelocityModelBundle | None = None,
    phone_gnss_accuracy_m: float | None = None,
) -> HybridPrediction:
    """Run E1 (model=None) or H1 without access to an evaluation reference."""

    leaked = (set(GNSS_DERIVED_FIELDS) | set(REFERENCE_ONLY_FIELDS)).intersection(
        blackout_sensor_data.columns
    )
    if leaked:
        raise ValueError(f"Estimator runtime input contains forbidden fields: {sorted(leaked)}")
    if model_bundle is not None and model_bundle.scaler.feature_order != FEATURE_ORDER:
        raise ValueError("Model/scaler runtime feature order mismatch.")
    # Phase 4 V4 supplies only the proven gravity alignment, causal filter,
    # calibrated gyro course, and conservative motion detector. Its trajectory
    # is not injected as an EKF measurement.
    conditioned = integrate_calibrated_dead_reckoning(
        blackout_sensor_data,
        calibration,
        phase4_settings,
        "V4_MOTION_AWARE",
    ).data
    frame = blackout_sensor_data.reset_index(drop=True)
    elapsed = frame["elapsed_s"].to_numpy(dtype=float)
    dt = conditioned["dt_s"].to_numpy(dtype=float)
    if np.any(dt > hybrid_settings.max_allowed_dt_s):
        raise ValueError("Estimator timestamp gap exceeds the frozen Phase 5 limit.")
    ekf = _initial_ekf(calibration, hybrid_settings, phone_gnss_accuracy_m)
    # Opt-in experiment: keep the training feature's meaning unchanged after
    # learned corrections. The historical frozen path remains the default.
    classical = (_initial_ekf(calibration, hybrid_settings, phone_gnss_accuracy_m)
                 if hybrid_settings.independent_classical_prior and model_bundle is not None else ekf)
    feature_template = build_runtime_feature_frame(frame, conditioned, np.zeros(len(frame)))
    feature_rows: list[np.ndarray] = []
    feature_window: deque[np.ndarray] = deque(
        maxlen=(model_bundle.config.window_steps if model_bundle is not None else 1)
    )
    records: list[dict[str, Any]] = []
    for index in range(len(frame)):
        ekf.predict(
            float(conditioned["conditioned_forward_acceleration_mps2"].iloc[index]),
            float(conditioned["gyro_course_rate_radps"].iloc[index]),
            float(dt[index]),
        )
        if classical is not ekf:
            classical.predict(float(conditioned["conditioned_forward_acceleration_mps2"].iloc[index]),
                              float(conditioned["gyro_course_rate_radps"].iloc[index]), float(dt[index]))
        stationary_attempted = False
        stationary_accepted = False
        stationary_nis = 0.0
        # Experimental planar no-slip constraint: left acceleration = -v*yaw_rate
        # for clockwise-positive course. Never divide by near-zero turn rate.
        if hybrid_settings.turning_velocity_constraint:
            rate = float(conditioned["gyro_course_rate_radps"].iloc[index])
            lateral = float(conditioned["conditioned_left_acceleration_mps2"].iloc[index])
            if 0.05 <= abs(rate) <= 1.5:
                turn_speed = -lateral / rate
                if 0.0 <= turn_speed <= 55.0:
                    variance = 4.0 + (0.5 / rate) ** 2
                    ekf.update_speed(turn_speed, variance)
                    if classical is not ekf:
                        classical.update_speed(turn_speed, variance)
        if (
            hybrid_settings.enable_stationary_updates
            and str(conditioned["motion_state"].iloc[index]) == "LIKELY_STATIONARY"
        ):
            stationary_attempted = True
            result = ekf.update_stationary()
            if classical is not ekf:
                classical.update_stationary()
            stationary_accepted = result.accepted
            stationary_nis = result.normalized_innovation_squared

        heading_attempted = False
        heading_accepted = False
        heading_nis = 0.0
        if hybrid_settings.enable_heading_updates and bool(
            conditioned["magnetic_heading_reliable"].iloc[index]
        ):
            heading_attempted = True
            result = ekf.update_heading_deg(
                float(conditioned["orientation_heading_deg"].iloc[index])
            )
            heading_accepted = result.accepted
            heading_nis = result.normalized_innovation_squared
            if classical is not ekf:
                classical.update_heading_deg(float(conditioned["orientation_heading_deg"].iloc[index]))

        classical_speed = float(classical.state[SPEED])
        current_features = feature_template.iloc[index].to_numpy(dtype=np.float32)
        current_features[-1] = classical_speed
        feature_rows.append(current_features.copy())
        feature_window.append(current_features)

        ml_attempted = False
        ml_accepted = False
        ml_skipped_ood = False
        ml_residual = 0.0
        ml_speed = classical_speed
        ml_nis = 0.0
        ml_variance = 0.0
        ood_exceedance = 0.0
        if (
            model_bundle is not None
            and len(feature_window) == model_bundle.config.window_steps
            and index % model_bundle.config.update_stride_steps == 0
        ):
            ml_attempted = True
            ml_residual, ood_exceedance = model_bundle.predict_window(np.vstack(feature_window))
            ml_speed = max(0.0, classical_speed + ml_residual)
            ml_variance = max(
                hybrid_settings.minimum_ml_variance_mps2,
                model_bundle.validation_residual_variance_mps2,
            )
            if ood_exceedance > hybrid_settings.ood_hard_exceedance:
                ml_skipped_ood = True
            else:
                if ood_exceedance > hybrid_settings.ood_soft_exceedance:
                    excess = ood_exceedance - hybrid_settings.ood_soft_exceedance
                    ml_variance *= 1.0 + hybrid_settings.ood_variance_inflation * excess * excess
                result = ekf.update_speed(ml_speed, ml_variance)
                ml_accepted = result.accepted
                ml_nis = result.normalized_innovation_squared

        covariance = ekf.covariance
        records.append(
            {
                "elapsed_s": elapsed[index],
                "dt_s": dt[index],
                "estimated_x_m": float(ekf.state[EAST]),
                "estimated_y_m": float(ekf.state[NORTH]),
                "estimated_speed_mps": float(ekf.state[SPEED]),
                "estimated_yaw_deg": float(np.degrees(ekf.state[YAW]) % 360.0),
                "accel_bias_estimate_mps2": float(ekf.state[ACCEL_BIAS]),
                "gyro_bias_estimate_radps": float(ekf.state[GYRO_BIAS]),
                "position_covariance_xx_m2": float(covariance[EAST, EAST]),
                "position_covariance_xy_m2": float(covariance[EAST, NORTH]),
                "position_covariance_yy_m2": float(covariance[NORTH, NORTH]),
                "position_covariance_trace_m2": float(covariance[EAST, EAST] + covariance[NORTH, NORTH]),
                "horizontal_position_sigma_m": ekf.horizontal_position_sigma_m,
                "speed_variance_mps2": float(covariance[SPEED, SPEED]),
                "yaw_variance_rad2": float(covariance[YAW, YAW]),
                "classical_speed_prior_mps": classical_speed,
                "ml_speed_measurement_mps": ml_speed,
                "ml_predicted_residual_mps": ml_residual,
                "ml_measurement_variance_mps2": ml_variance,
                "ml_ood_exceedance": ood_exceedance,
                "ml_update_attempted": ml_attempted,
                "ml_update_accepted": ml_accepted,
                "ml_update_rejected_innovation": ml_attempted and not ml_accepted and not ml_skipped_ood,
                "ml_update_skipped_ood": ml_skipped_ood,
                "ml_normalized_innovation_squared": ml_nis,
                "stationary_update_attempted": stationary_attempted,
                "stationary_update_accepted": stationary_accepted,
                "stationary_normalized_innovation_squared": stationary_nis,
                "heading_update_attempted": heading_attempted,
                "heading_update_accepted": heading_accepted,
                "heading_normalized_innovation_squared": heading_nis,
                "motion_state": str(conditioned["motion_state"].iloc[index]),
                "phase4_speed_mps": float(conditioned["estimated_speed_mps"].iloc[index]),
                "conditioned_forward_acceleration_mps2": float(
                    conditioned["conditioned_forward_acceleration_mps2"].iloc[index]
                ),
                "conditioned_left_acceleration_mps2": float(
                    conditioned["conditioned_left_acceleration_mps2"].iloc[index]
                ),
                "gyro_course_rate_radps": float(conditioned["gyro_course_rate_radps"].iloc[index]),
                "local_acceleration_x_mps2": float(conditioned["local_acceleration_x_mps2"].iloc[index]),
                "local_acceleration_y_mps2": float(conditioned["local_acceleration_y_mps2"].iloc[index]),
                "orientation_azimuth_deg": float(frame["orientation_azimuth_deg"].iloc[index]),
                "orientation_pitch_deg": float(frame["orientation_pitch_deg"].iloc[index]),
                "orientation_roll_deg": float(frame["orientation_roll_deg"].iloc[index]),
            }
        )
    output = pd.DataFrame(records)
    latitude, longitude = local_xy_to_geodetic(
        output["estimated_x_m"].to_numpy(dtype=float),
        output["estimated_y_m"].to_numpy(dtype=float),
        calibration.initialization.origin_latitude_deg,
        calibration.initialization.origin_longitude_deg,
    )
    output["estimated_latitude_deg"] = latitude
    output["estimated_longitude_deg"] = longitude
    numeric = output.select_dtypes(include=[np.number]).to_numpy(dtype=float)
    if not np.all(np.isfinite(numeric)):
        raise FloatingPointError("Phase 5 estimator produced NaN or infinity.")
    features = pd.DataFrame(np.vstack(feature_rows), columns=list(FEATURE_ORDER))
    return HybridPrediction(
        output,
        features,
        calibration,
        mode="H1_HYBRID_EKF_ML" if model_bundle is not None else "E1_EKF_CLASSICAL",
        algorithm=PHASE5_HYBRID_ALGORITHM if model_bundle is not None else PHASE5_EKF_ALGORITHM,
    )


def _as_raw_prediction(prediction: HybridPrediction) -> RawDRPrediction:
    return RawDRPrediction(
        prediction.data,
        prediction.calibration.initialization,
        algorithm=prediction.algorithm,
        integration_method="six-state EKF prediction with gated runtime-safe pseudo-measurements",
        coordinate_frame=prediction.coordinate_frame,
    )


def evaluate_hybrid_prediction(
    prediction: HybridPrediction,
    reference: EvaluationReference,
) -> HybridEvaluation:
    """Cross the VBOX boundary only after the runtime trajectory is complete."""

    base: RawDREvaluation = evaluate_raw_dr_prediction(_as_raw_prediction(prediction), reference)
    timeseries = base.timeseries.copy()
    speed_error = (
        timeseries["estimated_speed_mps"].to_numpy(dtype=float)
        - timeseries["reference_speed_mps"].to_numpy(dtype=float)
    )
    attempted = timeseries["ml_update_attempted"].to_numpy(dtype=bool)
    residuals = timeseries.loc[attempted, "ml_predicted_residual_mps"].to_numpy(dtype=float)
    metrics = {
        **base.metrics,
        "speed_mae_mps": float(np.mean(np.abs(speed_error))),
        "speed_rmse_mps": float(np.sqrt(np.mean(np.square(speed_error)))),
        "final_speed_error_mps": float(speed_error[-1]),
        "maximum_predicted_speed_mps": float(timeseries["estimated_speed_mps"].max()),
        "ml_residual_mean_mps": float(np.mean(residuals)) if residuals.size else 0.0,
        "ml_residual_std_mps": float(np.std(residuals)) if residuals.size else 0.0,
        "ml_updates_attempted": int(attempted.sum()),
        "ml_updates_accepted": int(timeseries["ml_update_accepted"].sum()),
        "ml_updates_rejected_innovation": int(timeseries["ml_update_rejected_innovation"].sum()),
        "ml_updates_skipped_ood": int(timeseries["ml_update_skipped_ood"].sum()),
        "heading_updates_attempted": int(timeseries["heading_update_attempted"].sum()),
        "heading_updates_rejected": int(
            (timeseries["heading_update_attempted"] & ~timeseries["heading_update_accepted"]).sum()
        ),
        "stationary_updates_accepted": int(timeseries["stationary_update_accepted"].sum()),
        "final_position_uncertainty_m": float(timeseries["horizontal_position_sigma_m"].iloc[-1]),
        "mean_position_uncertainty_m": float(timeseries["horizontal_position_sigma_m"].mean()),
        "maximum_position_uncertainty_m": float(timeseries["horizontal_position_sigma_m"].max()),
        "position_uncertainty_growth_m": float(
            timeseries["horizontal_position_sigma_m"].iloc[-1]
            - timeseries["horizontal_position_sigma_m"].iloc[0]
        ),
    }
    return HybridEvaluation(metrics, timeseries)
