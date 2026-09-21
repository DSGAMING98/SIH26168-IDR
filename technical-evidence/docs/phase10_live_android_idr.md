# Phase 10: live Android intelligent dead reckoning

## Scope and runtime boundary

Phase 10 turns the Phase 9.1 logger into a standalone phone localization prototype. `SensorLoggingService` produces the existing causal, approximately 10 Hz `LiveIdrSample`; `IdrEngine.process` is the engine's only runtime entry point. LIVE operation needs no laptop, cloud service, route, destination, VBOX reference, or network map.

The estimator never accepts an evaluation/reference object. A simulated blackout is isolated twice: Phase 9.1 makes `LiveIdrSample.gnss` null, and `IdrEngine` refuses GNSS whenever `simulatedBlackout` is true even if a malformed caller supplies a fix. Raw physical GNSS remains diagnostic/logger data and is not an estimator input.

## Causal processing

Each sample is processed once in timestamp order on the service's snapshot thread. The engine uses measured monotonic `dt` and rejects non-positive or larger-than-0.5-second steps instead of integrating across an unsafe scheduling interruption. It does not interpolate from the future.

1. Subtract Android gravity from accelerometer in device coordinates.
2. Rotate linear acceleration and gyroscope to the Android world frame using the current rotation-vector quaternion.
3. Project acceleration into the learned vehicle-forward/left frame.
4. Apply a causal first-order filter with a 0.30-second time constant.
5. Maintain ten-sample acceleration/gyroscope RMS windows for motion detection.
6. Predict and update the six-state EKF.
7. Every five complete samples after a 20-sample warm-up, run the frozen GRU and its OOD gate.

Missing attitude data produces a safe zero inertial input and degraded alignment rather than fabricated orientation.

## Alignment and coordinates

The app does not assume that phone +X is vehicle-forward. While GNSS is fresh and speed is at least 2.5 m/s, `VehicleAlignment` compares the rotation-vector device-top heading with GNSS bearing. It accepts the circular mean after at least five observations when circular concentration is at least 0.80. Before that, the UI reports `CALIBRATING`; absent attitude reports `DEGRADED`.

The first trusted GNSS fix defines a local origin. `CoordinateTransform` uses an equirectangular local tangent approximation with mean Earth radius 6,371,008.8 m: east is longitude difference scaled by the origin/point mean latitude and north is latitude difference. This is a local metric frame, not a claim about a dataset EPSG or survey-grade CRS. Estimated latitude/longitude is obtained by the inverse transform for display and logging.

## Classical estimator

`ClassicalEkf` has state `[east_m, north_m, speed_mps, yaw_rad_clockwise_from_north, accel_bias_mps2, gyro_bias_radps]`.

It propagates the complete 6x6 covariance with a Jacobian and process noise. Fresh GNSS can update position, speed, and bearing; the rotation vector can update yaw after vehicle alignment. Covariance is symmetrized and diagonals are floored after scalar updates. Likely-stationary samples apply a zero-speed measurement only when EKF speed (or trusted GNSS speed) is below 0.8 m/s, preventing a smooth moving vehicle from being mistaken for stationary.

Stationary thresholds are acceleration RMS below 0.18 m/s² and gyroscope RMS below 0.04 rad/s over ten samples. The deterministic stationary test ends at 0.0 m/s with approximately 4.4e-8 m displacement.

## Frozen ML correction and OOD safety

The unchanged Phase 5 checkpoint (`fa216978...0bb4ec`) is exported as 4,257 float32 parameters and implemented with the exact PyTorch GRU equations in pure Kotlin. The model consumes the frozen ten-feature order, 20 time steps, and frozen scaler/bounds. No training or fitting occurs on Android.

Three deterministic windows are evaluated in Python and Kotlin. Residual parity is enforced to `1e-4` m/s and OOD-exceedance parity to `1e-5`. Inference runs every five samples; the most recent correction is not re-applied on intermediate samples.

The UI/logger reports one of `ML_WARMING`, `ML_ACCEPTED`, `ML_OOD_LIMITED`, `ML_REJECTED`, or `ML_UNAVAILABLE`. Normalized bound exceedance at or below 0.5 is accepted with the frozen validation residual variance. Between 0.5 and 3.0 it is treated as a four-times-higher-variance speed measurement, reducing its Kalman influence; above 3.0 it is rejected. A missing/non-finite model result leaves the classical EKF safe and reports unavailable/rejected rather than claiming ML assistance.

## GNSS loss and recovery state machine

- `WAITING_FOR_GNSS`: no trusted origin/fix yet.
- `CALIBRATING`: GNSS is usable but vehicle alignment is incomplete.
- `GNSS_ACTIVE`: fresh GNSS and alignment are available.
- `GNSS_DEGRADED`: GNSS loss with incomplete alignment.
- `IDR_ACTIVE`: aligned phone-only propagation is active.
- `GNSS_VERIFYING`: GNSS has returned; two distinct fresh fixes are required.
- `GNSS_RECOVERING`: the verified target is approached at no more than 5 m/s correction rate.
- `ERROR`: a caught engine failure; the service continues to expose diagnostics.

The engine uses the exact Phase 9.1 physical-fix monotonic timestamp (with an age-derived compatibility fallback), so repeating a stored fix at 10 Hz does not count as repeated fresh evidence. Recovery requires at least 15 runtime samples and innovation within 5 m before returning to active. The synthetic test's recovery has an 8.34 m initial innovation, a 0.5 m maximum per-sample correction, 0.08 m final error, and returns to `GNSS_ACTIVE`.

Horizontal uncertainty is the larger horizontal one-axis standard deviation, `sqrt(max(P_east,east, P_north,north))`. The state exposes this value and a qualitative `HIGH`/`MEDIUM`/`LOW` confidence derived from uncertainty. Uncertainty grows under dead reckoning and contracts under trusted measurements; it is an engineering covariance indicator, not a calibrated radial confidence guarantee.

## User interface

The single activity has three deliberately separate tabs:

- **LIVE**: state chip, offline local trajectory, current marker/heading, uncertainty circle, speed, heading, DR duration, confidence, Start/Stop, and development GNSS-loss control.
- **DEMO REPLAY**: always labelled `DEMO REPLAY • SYNTHETIC • NOT LIVE`; Start/Pause/Reset/Trigger Loss drives the same `IdrEngine` with a route-free synthetic fixture.
- **DIAGNOSTICS**: Phase 9.1 sensor rates/availability, GNSS provider/callback/satellite/TTFF observability, alignment, ML/OOD, engine timing, and export.

`TrajectoryView` is a self-contained ENU canvas with grid, north arrow, scale, origin, state-coloured trail, marker, and uncertainty circle. It is not a road map and does not imply map matching. The activity applies all four system-window insets to the root safe area; the main screen avoids the earlier diagnostic text wall. Source/layout review was completed, but no emulator or physical rendering was available in this run.

## Demo and logging

The deterministic demo contains 270 samples at 10 Hz: six seconds of GNSS, ten seconds of complete runtime GNSS loss, then verified and bounded reacquisition. It is synthetic, contains no private recording and no hidden reference/route. During blackout it advances 59.99 m and exercises `GNSS_ACTIVE -> IDR_ACTIVE -> GNSS_VERIFYING -> GNSS_RECOVERING -> GNSS_ACTIVE`.

Phase 9 files and schemas remain operational. Phase 10 adds `idr_output.csv` (schema version 1 in session metadata) with timestamps, local/geodetic estimate, speed/heading/uncertainty, confidence, localization/alignment/motion/ML states, OOD/residual, DR duration, innovation/correction, engine timing, and GNSS acquisition state. Use:

```powershell
.venv\Scripts\python.exe tools\inspect_phase10_idr_output.py <exported-session-directory>
```

## Build and install

From the repository root:

```powershell
$env:JAVA_HOME = 'C:\Program Files\Android\openjdk\jdk-21.0.8'
$env:ANDROID_HOME = 'C:\Users\Prajwal\AppData\Local\Android\Sdk'
android\gradlew.bat -p android testDebugUnitTest assembleDebug --offline
.venv\Scripts\python.exe -m pytest -q
```

The debug APK is `android/app/build/outputs/apk/debug/app-debug.apk`. Install through Android Studio or, with a trusted connected phone and Android platform tools on `PATH`, run `adb install -r android\app\build\outputs\apk\debug\app-debug.apk`.

## Physical smoke test

1. Install the debug APK and grant notifications, motion sensors, and precise location.
2. Go outdoors under open sky and open **DIAGNOSTICS**. Wait for `FRESH`, nonzero physical callbacks, a first-fix time, and reasonable satellite-used count.
3. Mount the phone securely and keep the screen readable without handling it while driving. A second person should operate/observe the app.
4. Open **LIVE**, start recording, and drive straight above 2.5 m/s until alignment becomes `READY` and state becomes `GNSS_ACTIVE`.
5. On a safe low-traffic segment, let the passenger enable simulated GNSS loss. Verify `IDR_ACTIVE`, increasing DR duration, continued marker motion, and changing uncertainty while runtime GNSS is masked.
6. Disable loss. Verify `GNSS_VERIFYING`, then bounded `GNSS_RECOVERING`, then `GNSS_ACTIVE` without a hard teleport.
7. Stop, export the session ZIP, and inspect `runtime_10hz.csv`, `events.csv`, and `idr_output.csv`. Confirm blackout runtime GNSS columns are empty and `blackout_masks_real_fix=true`.
8. Separately run **DEMO REPLAY** indoors to show the deterministic story; never present it as a live drive.

Do not operate the phone while driving and do not use this prototype for safety-critical navigation.

## Known limitations and Phase 11 requirements

Phase 10 proves buildable, deterministic, causal on-device engineering—not real-road accuracy. It has no road graph or planned route, no commercial navigation, and no calibrated covariance study. Local equirectangular coordinates are intended for journey-scale display. Magnetic/rotation-vector orientation and phone mounting can shift across devices. The frozen S1 GRU transfers inconsistently across domains and is therefore OOD-gated. Universal sub-10% drift is not claimed.

Phase 11 must validate on physical drives: state/alignment behavior across mounting orientations, blackout trajectory error against an independent reference, stationary and stop-go stability, repeated GNSS loss/recovery, covariance calibration, thermal/battery/background endurance, UI readability/safe-area behavior on actual devices, exported-schema completeness, and whether ML helps or is rejected on each target device. No Phase 11 implementation is included here.
