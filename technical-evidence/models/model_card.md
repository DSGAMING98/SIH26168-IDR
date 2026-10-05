# Phase 5 Velocity GRU

## What it predicts

A bounded correction to the causal classical EKF forward-speed estimate. It never predicts latitude, longitude, or a trajectory.

## Runtime sensor inputs

The fixed 2-second history contains: conditioned_forward_acceleration_mps2, conditioned_left_acceleration_mps2, gyro_course_rate_radps, gyro_magnitude_radps, gravity_magnitude_mps2, magnetic_magnitude_ut, motion_accel_rms_mps2, motion_gyro_rms_radps, is_likely_stationary, classical_speed_mps. Every feature is derived from GNSS-free phone sensors or the causal EKF state.

## Training and exclusions

The model used IO-VNBD S1 time-blocked development intervals. VBOX speed was used offline only as the target label. All five benchmark intervals and the preselected surprise holdout were quarantined with 120 seconds before blackout start and 60 seconds after blackout end. Scaling used training rows only; checkpoint selection used validation loss only.

## Size and limitations

The one-layer 32-unit GRU has 4,257 parameters. It was trained on one journey and is not evidence of cross-device or cross-dataset generalization. OOD feature exceedance reduces or removes its EKF influence.

## Android deployment (current app 2.4.0)

The frozen checkpoint has a dependency-free Kotlin forward pass in `technical-evidence/android/android/app/src/main/java/org/sih26168/idrlogger/engine/FrozenVelocityModel.kt`. `CausalMlVelocity` maintains the 20-step history and applies the fixed scaler/OOD limits. `IdrEngine` accepts only bounded, gated speed-residual measurements. Phase 10 Python/Kotlin golden-vector parity is recorded in the evidence bundle. No TFLite, ONNX or cloud inference is used by the app. This deployment update does not change the Phase 5 training record or checkpoint.
