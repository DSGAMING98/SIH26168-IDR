# Phase 8 Cross-Dataset Validation

## Question and protocol

Phase 8 asks whether the IO-VNBD S1 system remains useful on unseen devices, locations, rates, and sensor characteristics. It is a zero-shot validation, not training. The Phase 5 GRU/checkpoint/scaler and Phase 6/7 configurations are unchanged. No target label fits a scaler, mounting, threshold, fallback, window, or model parameter.

The target windows were frozen in `configs/phase8/cross_dataset_zero_shot.json` before target ground-truth rows were read. Scenario selection used session/device diversity and only causal runtime WLS displacement-speed and gyroscope activity. Four fixed windows cover two phones and two cities. The reference later showed `SDC_MTV_10_STEADY` to be stationary; it remains in the result as evidence that the selection was not revised after evaluation.

## Local capability audit

| Dataset | Classification | Core IMU | Runtime GNSS | Reference | Decision |
|---|---|---:|---:|---:|---|
| IO-VNBD S1 | Baseline / fully compatible | Yes | Yes | Synchronized VBOX | Locked source-domain comparison only |
| Google Smartphone Decimeter 2022 | Partially compatible | Accel/gyro/mag | WLS ECEF | Position/speed/bearing | Selected for zero-shot core comparison; no defensible WLS accuracy for Phase 7 |
| WHU Smartphone Dataset | Reference-only | No local phone IMU | Yes | Separate reference files | Cannot run the frozen inertial feature set |
| MoRPI | Partially compatible | Accel/gyro only | No | No compatible time-resolved track found | Missing magnetometer, GNSS initialization, mounting semantics, and reference |
| PPC Dataset | Unusable locally | Payload absent | Payload absent | Payload absent | Local tree contains documentation/LFS metadata only |
| GREAT Dataset | Unusable locally | Payload absent | Payload absent | Payload absent | Local tree contains documentation/figures/tools only |

The complete per-field audit—including timestamps, every sensor/navigation/reference field, metadata, rates, axes, coordinate frames, units, and reference suitability—is in `results/phase8/capability_matrix.csv` and JSON. `UNKNOWN` is used where inspected local material did not establish semantics.

## Canonical isolation boundary

`CanonicalRuntimeSession` contains only phone sensor rows, separately held runtime GNSS, and non-trajectory metadata. `RuntimeBlackout` exposes strictly pre-blackout sensor/GNSS history plus a sensor-only half-open blackout. `CanonicalEvaluationReference` is a different type loaded by a different adapter method.

The runtime loader never opens `ground_truth.csv`. Every Raw/Phase 4/EKF/Hybrid prediction completes before the orchestration code calls `load_reference()`. Evaluation then interpolates the 1 Hz reference to completed 10 Hz prediction timestamps in a separate module. Estimator APIs never accept the reference object.

Canonical required sensor fields are elapsed/UTC time and accelerometer, gyroscope, and magnetometer XYZ with explicit SI/microtesla units. Optional gravity/orientation fields are preserved where genuinely supplied. Runtime GNSS uses latitude, longitude, speed, and course, with optional altitude/accuracy. Reference contains position, speed, bearing, and optional altitude. Availability is explicit; missing required model sensors cause a clear error rather than zero fabrication.

## Smartphone Decimeter adapter

- Source IMU columns: `MessageType`, `utcTimeMillis`, `MeasurementX/Y/Z`, `BiasX/Y/Z`. `UncalAccel`, `UncalGyro`, and `UncalMag` units are m/s², rad/s, and microtesla according to the local supplemental header. Calibrated values are `Measurement - Bias`, following Android uncalibrated-sensor semantics.
- Source runtime GNSS: unique `utcTimeMillis` WLS ECEF XYZ from `device_gnss.csv`. It converts with the WGS84 ellipsoid. Runtime speed/course are five-second backward displacement and bearing; no future point is used.
- Source reference: `ground_truth.csv` latitude/longitude, `SpeedMps`, and `BearingDegrees`, loaded only in the evaluator phase.
- Native rates: selected acceleration/gyro streams are approximately 52.63 Hz, magnetometer 100 Hz, WLS and reference approximately 1 Hz.
- Effective rate: 10 Hz. Each output bin is the arithmetic mean over the right-closed interval `(previous end, current end]`; every source timestamp is no later than the output timestamp. Actual elapsed timestamps and `dt` are retained.
- Gravity: two-second causal first-order accelerometer low-pass direction, normalized to 9.80665 m/s².
- Mounting: the local files do not document phone-to-vehicle mounting. The adapter therefore estimates one fixed horizontal motion axis from the principal horizontal acceleration direction in the strictly pre-blackout 60-second runtime-only IMU window. This is an explicit assumption. It never minimizes reference error.
- Yaw: magnetic heading of that axis is aligned to five-second causal WLS course by the frozen Phase 4 pre-blackout calibration. Gyro course rate follows right-handed angular velocity projected on Up and the frozen S1 course-sign interface.
- Frozen estimator bridge: a level pseudo vehicle frame (+X forward, +Y left, +Z up) supplies the existing Phase 4/5 code. It does not fabricate a missing sensor; all required source sensors exist.

## Frozen results

Drift is final blackout-relative error divided by reference distance. It is undefined for the stationary 10-second window.

| Scenario | Start / duration (s) | Device/location | Distance (m) | Raw % | Phase 4 % | EKF % | Hybrid % | Hybrid final / RMSE / P95 (m) | Hard OOD |
|---|---:|---|---:|---:|---:|---:|---:|---|---:|
| `SDC_MTV_10_STEADY` | 240 / 10 | Pixel 4 XL / Mountain View | 0.000 | N/A | N/A | N/A | N/A | 0.060 / 0.494 / 1.314 | 100.000% |
| `SDC_MTV_30_DYNAMIC` | 968 / 30 | Pixel 4 XL / Mountain View | 337.242 | 124.647 | 24.358 | 23.308 | 40.866 | 137.819 / 49.628 / 114.396 | 64.286% |
| `SDC_MTV_60_HIGHER_SPEED` | 1800 / 60 | Pixel 4 XL / Mountain View | 1,582.816 | 7.968 | 56.633 | 80.783 | 81.323 | 1,287.194 / 689.583 / 1,219.029 | 0.000% |
| `SDC_LAX_30_DYNAMIC` | 1577 / 30 | Pixel 5 / Los Angeles | 495.938 | 120.262 | 72.283 | 64.151 | 27.522 | 136.494 / 58.925 / 115.707 | 0.000% |
| **Moving median** | — | — | — | **120.262** | **56.633** | **64.151** | **40.866** | — | — |

The locked IO-VNBD four-standard medians were 95.920% Raw, 68.048% Phase 4 V5, 24.009% EKF, and 25.444% Hybrid. These dataset-level medians are not combined into a deceptive global average.

On the three moving target windows, EKF beats raw twice. Hybrid beats EKF once and degrades twice. The result is **MODERATE GENERALIZATION**: the architecture supplies useful behavior in some unseen-device cases and the runtime OOD safety reacts, but neither the S1 dynamics nor the learned correction transfers uniformly. It is not a general <10% claim.

## Domain shift and OOD

The frozen S1 scaler is preserved. Target conditioned acceleration, course rate, gravity magnitude, and classical speed generally remain within their S1 feature bounds. Magnetic magnitude is the dominant shift, outside S1 training bounds for a median 94.5% of scenario samples, with maximum normalized exceedance above 6.2. Some gyro/motion RMS windows also exceed their bounds. The hard-OOD gate skips ML attempts rather than disabling the protection: all attempted ML updates are skipped in the stationary window and 64.286% in `SDC_MTV_30_DYNAMIC`. The longer MTV and LAX windows have accepted updates; those respectively slightly degrade and substantially improve EKF, demonstrating inconsistent learned transfer.

Direct target-only input statistics for accelerometer/gyro/magnetometer magnitude, effective sample interval, adapted gravity, and causal classical speed are in `domain_shift_summary.*`; normalized per-feature comparisons are in `feature_shift.*`.

## Phase 6, Phase 7, and performance

The S1 OSM graph is geographically invalid in Mountain View/Los Angeles and was not applied. No new map was downloaded. Phase 7 is not forced: the selected WLS stream has no defensible per-fix accuracy field required by the frozen verification/uncertainty contract. This makes both components `NOT_APPLICABLE`, not failed or silently approximated.

Warm `SDC_MTV_60_HIGHER_SPEED` Hybrid processing includes only in-memory GNSS-free Phase 4 conditioning, EKF propagation/updates, frozen GRU inference, and frozen OOD handling. It measured 1,394.6 samples/s and 0.717 ms/sample versus 10 Hz. Loading, adapter/resampling, pre-blackout calibration, reference loading, offline evaluation, serialization, and plotting are excluded and timed separately. P95 is not reported because the frozen estimator exposes a batch entry point and Phase 8 did not alter the algorithm solely to instrument it.

## Reproduction and limitations

```powershell
.venv\Scripts\python.exe tools\run_phase8_validation.py
.venv\Scripts\python.exe tools\run_phase8_validation.py --scenario SDC_MTV_60_HIGHER_SPEED --output results\phase8_reproduction
.venv\Scripts\python.exe -m pytest -q
```

Known limitations are the one independent dataset family, two devices, four short windows, noisy runtime WLS initialization, absent documented device mounting, gravity/mounting approximations, magnetic shift, inconsistent ML benefit, uncalibrated EKF covariance, no cross-location map, and no fair Phase 7 cross-dataset input. Source-file and locked-artifact hashes are recorded in `integrity_manifest.json`.
