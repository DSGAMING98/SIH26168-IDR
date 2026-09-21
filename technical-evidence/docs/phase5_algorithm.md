# Phase 5 Hybrid EKF and Velocity GRU

## Runtime/reference contract

The runtime estimator accepts only GNSS-free Phase 2 sensor rows, a strictly pre-blackout phone initialization/Phase 4 calibration, frozen configurations, and optionally the frozen GRU bundle. It rejects phone-GNSS and VBOX/reference columns. `EvaluationReference` is accepted only by the separate post-prediction evaluator. VBOX speed is used offline as a supervised label; no VBOX value is available to inference.

The model feature order is fixed to conditioned forward and lateral acceleration, calibrated gyro course rate, gyro magnitude, gravity magnitude, magnetic magnitude, motion acceleration RMS, motion gyro RMS, likely-stationary flag, and the causal classical EKF speed. It contains no latitude, longitude, scenario ID, absolute journey timestamp, VBOX field, or future sample.

## EKF state and process

The state is:

`x = [east, north, forward_speed, yaw, residual_accel_bias, residual_gyro_bias]`

Yaw is radians clockwise from North in a local spherical ENU tangent approximation. For measured `dt`, filtered forward acceleration `a`, and calibrated gyro course rate `omega`:

`d = speed*dt + 0.5*(a - accel_bias)*dt^2`

`east' = east + d*sin(yaw)`

`north' = north + d*cos(yaw)`

`speed' = speed + (a - accel_bias)*dt`

`yaw' = wrap(yaw + (omega - gyro_bias)*dt)`

Bias states are random walks. Because Phase 4 already removes reliable pre-blackout bias, EKF biases represent residuals and start from zero-mean priors. The Jacobian includes position derivatives with respect to speed, yaw, and acceleration bias, plus `F[speed,accel_bias] = -dt` and `F[yaw,gyro_bias] = -dt`.

Q is generated through an explicit noise-input matrix: acceleration noise 0.8 m/s² affects displacement and speed; yaw-rate noise 0.08 rad/s affects yaw; acceleration-bias random walk is 0.015 m/s²/sqrt(s); gyro-bias random walk is 0.0015 rad/s/sqrt(s). These engineering values were frozen before held-out execution and were not chosen from benchmark drift.

Initial position sigma is the larger of phone GNSS accuracy and 3 m. Speed, yaw, residual acceleration-bias, and residual gyro-bias sigmas are 2 m/s, at least 15 degrees, 0.25 m/s², and 0.03 rad/s. No VBOX benchmark error initializes covariance.

## Measurement models and gates

All updates are scalar with normalized innovation squared `NIS = innovation^2 / S`; updates use the Joseph covariance form and covariance is symmetrized after every step.

- Stationary: `z=0`, `H=[0,0,1,0,0,0]`, sigma 0.25 m/s, NIS gate 100.
- Heading: wrapped yaw innovation, sigma 15 degrees, NIS gate 9. It is implemented but disabled in the frozen default because Phase 4 V5 magnetic correction was inconsistent.
- ML speed: `z=max(0, classical_speed + predicted_residual)`, speed-state H, NIS gate 9. R is 128.7822 m²/s² from non-benchmark validation residual variance with a 0.25 m²/s² floor.

The training-only scaler stores 0.5/99.5 percentile normalized bounds. Exceedance above 0.5 inflates ML R quadratically; exceedance above 3 skips ML. This prevents unfamiliar sensor patterns from dominating the EKF.

`sqrt(Pxx + Pyy)` is reported as estimated horizontal position uncertainty. It is not a calibrated 95% confidence radius.

## ML architecture and training

The learned target is `VBOX reference speed - classical EKF speed`. A one-layer GRU with 32 hidden units and one linear/tanh head bounds the correction to ±12 m/s. It consumes a 20-step, approximately 2-second history ending at the current sample and updates the EKF every five samples. The final model has 4,257 parameters and a 21,649-byte checkpoint.

Seed 26168 controls Python, NumPy, and PyTorch. Training uses CPU Adam, Huber loss, gradient clipping, early stopping, and best-validation checkpoint selection. The scaler is fitted only on 24,395 training rows. There are 11,818 training windows and 3,489 validation windows. The frozen epoch-14 checkpoint reduced non-benchmark validation speed MAE from 12.226 to 6.814 m/s and RMSE from 18.756 to 12.635 m/s.

## Blocked split and quarantine

No row-random split is used. Training blocks are `[60,200)`, `[450,1000)`, `[1300,1900)`, `[2200,2800)`, `[3195,3375)`, `[3735,3975)`, and `[5015,5174.4)`. Validation blocks are `[1000,1300)`, `[1900,2200)`, and `[3975,4095)`. Independent development outages stay inside those blocks; no window crosses a boundary.

Quarantine intervals are `[200,390)` for 10 s, `[4435,4645)` for 30 s, `[4095,4335)` for 60 s, `[3375,3675)` for 120 s, `[4730,4955)` for the 45 s judge window, and `[2880,3135)` for the preselected 75 s surprise. Each includes 120 seconds before blackout start and 60 seconds after blackout end. These rows are absent from training, validation, scaling, checkpoint selection, and EKF tuning.

## Held-out result and limitations

Hybrid standard drift is 22.655%, 18.571%, 28.232%, and 38.480% for 10/30/60/120 seconds. The 45-second judge result is 52.259%; the surprise result is 3.855%. Median standard drift is 25.444%, materially better than Phase 4 V4 at 57.979%, but classical E1 EKF has a slightly better 24.009% standard median. ML helps 30 s, 60 s, and the surprise case, is nearly neutral on 45 s, and hurts 10 s and 120 s versus E1. This is retained rather than retuned.

The mandatory ablation contains B0 Raw, B1 Phase 4 V4, B2 Phase 4 V5, E1 classical EKF, and H1 hybrid EKF+ML. Optional M1 was omitted because producing a second ML-speed trajectory outside the EKF would duplicate the full propagation/evaluation path while bypassing the uncertainty-aware measurement design; validation speed metrics already isolate the learned residual's effect.

The model has seen only S1, validation error remains large, and covariance has not been statistically calibrated. Speed correction cannot fix every heading error. Phase 6 may consume the trajectory/covariance for multi-hypothesis map matching, but must preserve the reference boundary and report the inertial-only evidence. Phase 5 includes no map matching, road graph, GNSS reacquisition, or Android application.
