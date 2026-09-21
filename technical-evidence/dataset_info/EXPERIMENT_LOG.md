# Experiment Log

## M1-001 - IO-VNBD S1 load, synchronization, and visualization

Date: 2026-08-31  
Phase: 0-1  
Status: Passed

### Objective

Load one real synchronized IO-VNBD journey, validate both clocks and schemas, create the required plots, and determine whether the session is ready for controlled GNSS blackout simulation.

### Selection

Session `S-S1` / `V-S1` was selected because the bundled paper documents 86.3 minutes, 38.16 km, nine roundabouts, five reverse manoeuvres, hills, a B-road/ring-road mix, and hard braking. It is long and diverse enough to later select straight, turning, stopping, and extended blackout windows.

### Inputs

| Stream | Project-relative file | Rows | Verified SHA-256 |
|---|---|---:|---|
| Smartphone | `data/cache/io_vnbd/S1/S-S1.csv` | 51,746 | `8c4d2678fd79cce7c819437a7d85d7d5cb9e47a63dac7d171ead3f9d052deff1` |
| Vehicle reference | `data/cache/io_vnbd/S1/V-S1.csv` | 51,746 | `29e92ed9bcb2d711e651246675c435b3f9499c040cfcad367624e8720c0dc891` |

The checksums match the corresponding Git LFS pointer object IDs in the untouched source tree.

### Command

```powershell
& 'C:\Users\Prajwal\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' tools\inspect_io_vnbd.py --session S1
```

Tests:

```powershell
& 'C:\Users\Prajwal\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests -v
```

### Results

| Metric | Smartphone | Vehicle reference |
|---|---:|---:|
| Samples | 51,746 | 51,746 |
| Duration | 5,174.499 s | 5,174.500 s |
| Median interval | 0.100 s | 0.100 s |
| Approximate rate | 10.0 Hz | 10.0 Hz |
| Missing timestamps | 0 | 0 |
| Duplicate timestamps | 0 | 0 |
| Non-monotonic timestamps | 0 | 0 |
| Gaps above 1.5 x median | 0 | 0 |
| Maximum interval | 0.111 s | 0.101 s |
| Cumulative GPS track | 37.162 km | 38.044 km |

Synchronization residual using independent elapsed clocks:

- Median phone-minus-VBOX residual: -1.0 ms
- 95th-percentile absolute residual: 1.0 ms
- Maximum absolute residual: 10.0 ms

All source cells are populated and all smartphone wall-clock timestamps parse successfully.

### Unit checks

- Smartphone speed source label is incorrect: numeric values behave as m/s, not km/h. A corrected km/h series is derived by multiplying by 3.6.
- Vehicle height source label is incorrect: numeric values are metre-scale, not kilometre-scale.
- CSV gyroscope X/Y/Z headers supersede the duplicated pitch label in PDF Table 4.

### Generated evidence

- `results/io_vnbd/s1/s1_gnss_trajectory.png`
- `results/io_vnbd/s1/s1_accelerometer.png`
- `results/io_vnbd/s1/s1_gyroscope.png`
- `results/io_vnbd/s1/s1_speed.png`
- `results/io_vnbd/s1/s1_heading_orientation.png`
- `results/io_vnbd/s1/session_summary.json`

Visual QA findings:

- Phone and VBOX trajectories overlap coherently over the complete route.
- Accelerometer Z remains near gravitational acceleration with plausible driving/vibration excursions; X/Y remain centered near zero with motion bursts.
- Gyroscope traces show low stationary activity and repeated turn/motion events without visible clipping.
- After the documented unit correction, smartphone and VBOX speed profiles overlap coherently; VBOX retains finer 10 Hz detail.
- VBOX heading and smartphone GPS orientation broadly agree. Phone azimuth/pitch/roll also show orientation wrapping and mount-specific offsets, reinforcing the need for later frame-alignment work.

### Problems discovered

1. Local IO-VNBD CSV/ZIP sources are LFS stubs, not payloads.
2. Published S1 count differs from the actual pair by 44 rows.
3. Smartphone speed and vehicle height source units are mislabeled.
4. PDF gyroscope labels contain a duplicated pitch row.
5. Phone GNSS solution values change much more slowly than the paper's stated 1 Hz rate.
6. Datum/EPSG and timezone are not explicit in the bundle.

### Conclusion

S1 is ready for Phase 2 because it has complete synchronized 10 Hz IMU/reference rows, validated clocks, a long varied route, and reproducible loading. Phase 2 must use VBOX GPS only as hidden evaluation reference and must not leak it into the phone-only localization input.

## M2-001 - Controlled GNSS blackout simulator and benchmark

Date: 2026-08-31
Phase: 2
Status: Passed

### Objective and protocol

Create a reusable deterministic harness that masks GNSS by synchronized elapsed time while preserving non-GNSS phone sensors and keeping VBOX strictly on the evaluation side. Blackout intervals use half-open semantics: `start_s <= elapsed_s < start_s + duration_s`; zero/negative durations and out-of-session windows are rejected.

### Runtime/reference separation

- Runtime sensor frame: time, accelerometer, gravity, gyroscope, magnetometer, Android azimuth/pitch/roll, and `gnss_available`; no GNSS measurement columns.
- Runtime GNSS observations: GNSS-derived columns only at available timestamps; all blackout rows are removed.
- Hidden evaluation reference: a distinct VBOX wrapper retained only for scenario summaries, distance calculation, validation, and visualization.
- Metadata: requested/actual boundaries, sample count, sampling tolerance, scenario label, output paths, and validation results.

GPS position, altitude, source/normalized speed, accuracy, GPS orientation, and satellite status are classified as GNSS-derived. The distinct Android phone-orientation azimuth/pitch/roll fields remain runtime-visible based on the bundled IO-VNBD schema.

### Commands

```powershell
python tools/simulate_blackout.py --session S1 --config configs/blackouts/io_vnbd_s1.json
python tools/simulate_blackout.py --session S1 --start 4850 --duration 45 --scenario-id S1_45_CLI_CUSTOM --scenario-type dynamic_custom_duration --output-dir results/blackouts/io_vnbd/s1/custom_45
python -m unittest discover -s tests -v
```

### Standard results

| ID | Start (s) | Requested duration (s) | Actual masked duration (s) | Masked samples | Type | VBOX reference distance (m) |
|---|---:|---:|---:|---:|---|---:|
| `S1_10_STEADY` | 320.0 | 10 | 10.001 | 100 | Straight/steady | 154.156 |
| `S1_30_TURNING` | 4555.0 | 30 | 29.900 | 299 | Turning/dynamic | 200.925 |
| `S1_60_STOP_GO` | 4215.0 | 60 | 60.001 | 600 | Stop-go/low-speed | 262.794 |
| `S1_120_HIGHER_SPEED` | 3495.0 | 120 | 120.000 | 1200 | Higher speed | 1706.385 |

The standalone 45-second CLI run at 4850.0 seconds masked 450 samples for an actual 45.000 seconds and covered 226.679 m on the VBOX reference. Repeated execution produced the same mask.

### Metrics and coordinates

Reference path length and point-to-point horizontal errors use the haversine great-circle formula with the IUGG mean Earth radius of 6,371,008.8 m. A compact local east/north helper uses a documented spherical equirectangular tangent approximation around an explicit origin; it does not assert an EPSG code. Utilities define final, mean, RMSE, maximum, 95th-percentile position error and drift percentage, returning undefined drift for zero reference distance. They were tested but not invoked as model results because Phase 2 has no estimator.

### Validation and evidence

All five Milestone 1 tests and nineteen new blackout/evaluation tests pass (24 total). Tests cover masking, availability outside the window, explicit GNSS leakage prevention, retained IMU values, isolated/preserved VBOX reference, unchanged input checksums, sampling-tolerance duration, invalid windows, zero/negative duration, determinism, alignment, standard durations, a custom duration, and metric edge cases.

Generated artifacts are under `results/blackouts/io_vnbd/s1/`: benchmark configuration copy, JSON/CSV summaries, runtime schema, sample-level masks, full-route overview, zoomed per-window trajectory plots, representative GNSS availability/IMU timeline, and standalone custom-CLI evidence.

### Limitations

Datum/EPSG and timezone remain unspecified. VBOX remains an evaluation reference rather than claimed survey-grade truth. Scenario labels are data-derived motion descriptions rather than invented road semantics. Future algorithms must consume only the runtime domain causally; no estimator or localization result was created in Phase 2.

## M3-001 - Raw inertial dead-reckoning baseline

Date: 2026-08-31
Phase: 3
Status: Passed

### Environment and leakage boundary

Execution used `C:\Users\Prajwal\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`, Python 3.12.13. The workstation's unqualified `python` command resolves to Python 2.7.11 and was not used.

The estimator API is `integrate_raw_dead_reckoning(blackout_sensor_data, initialization, max_allowed_dt_s)`. It has no reference argument. `blackout_sensor_data` comes from the Phase 2 runtime frame and is rejected if any forbidden GNSS field or GNSS-available row is present. Initialization construction rejects any phone sensor or GNSS row at or after the requested blackout start. VBOX is passed only to `evaluate_raw_dr_prediction` after the prediction exists.

### Raw equations and conventions

Device linear acceleration is:

`a_device = accelerometer_device - gravity_device`

Both source vectors are recorded in m/s² in the same phone axes. The bundled paper states that gravity per axis is provided to correct measured acceleration and that mounted +X was intended to follow travel.

The frozen Android orientation interpretation is device +X right, +Y toward the display top, +Z out of the screen; azimuth is clockwise from magnetic North about -Z, pitch is about +X, and roll is about +Y. Angles are converted from degrees to radians. The device-to-navigation rotation is `Rz(-azimuth) @ Rx(-pitch) @ Ry(roll)`. Navigation is local ENU: X East, Y North, Z Up. This choice was validated with identity and 90-degree synthetic rotations and was not selected by VBOX error.

Initial local velocity uses phone GPS speed and phone GPS course: `v_east = speed * sin(course)` and `v_north = speed * cos(course)`. The phone GNSS coordinate is the local origin. With measured positive `dt`, trapezoidal integration is:

`v_k = v_(k-1) + 0.5 * (a_(k-1) + a_k) * dt_k`

`p_k = p_(k-1) + 0.5 * (v_(k-1) + v_k) * dt_k`

No filtering, bias calibration, mounting correction, damping, stop detection, zero-velocity update, speed clamp, road constraint, or reference-derived adjustment is applied.

### Evaluation method

Absolute error compares the phone-origin prediction with synchronized VBOX and therefore includes the pre-existing phone/VBOX offset. Relative error independently rebases predicted and VBOX displacement at the first masked sample, then compares displacement through the outage. The primary drift definition is relative final error divided by VBOX reference path distance times 100. VBOX remains an evaluation reference, not claimed survey-grade ground truth.

### Results

| Scenario | Actual s | Distance m | Final m | Drift % | Mean m | RMSE m | Max m | P95 m | Init speed m/s | GNSS row age s | Solution age s | Max predicted speed m/s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `S1_10_STEADY` | 10.001 | 154.156 | 12.804 | 8.306 | 7.629 | 8.569 | 12.808 | 12.757 | 15.34 | 0.001 | 7.000 | 16.533 |
| `S1_30_TURNING` | 29.900 | 200.925 | 135.297 | 67.337 | 71.732 | 82.154 | 135.297 | 130.446 | 13.71 | 0.001 | 7.001 | 23.867 |
| `S1_60_STOP_GO` | 60.001 | 262.794 | 327.185 | 124.503 | 122.906 | 149.542 | 327.185 | 296.937 | 10.42 | 0.100 | 8.000 | 10.489 |
| `S1_120_HIGHER_SPEED` | 120.000 | 1706.385 | 2354.887 | 138.004 | 956.492 | 1213.102 | 2354.887 | 2196.796 | 10.92 | 0.099 | 4.000 | 21.952 |
| `S1_45_DYNAMIC_CUSTOM` | 45.000 | 226.679 | 228.020 | 100.592 | 91.580 | 123.895 | 228.020 | 210.831 | 0.00 | 0.001 | 44.000 | 7.962 |

Absolute phone-GNSS/VBOX initialization offsets were 111.787, 90.619, 109.347, 46.650, and 3.318 m respectively. Absolute final errors were 111.524, 220.787, 284.236, 2368.636, and 231.287 m. No prediction exceeded the 70 m/s diagnostic threshold.

### Error-growth interpretation

Observed results show rapidly increasing displacement error with duration and dynamic complexity. The 30-second turning path diverges despite bounded speed. In the 60-second stop-go segment, VBOX reaches zero while raw DR cannot identify the stop. The 120-second trajectory travels in a substantially different direction, even though predicted speed remains within 21.952 m/s. The custom scenario starts at zero phone speed but its held GNSS solution is 44 seconds old.

Likely contributors, ranked for Phase 4 investigation, are orientation/mounting-frame ambiguity, accelerometer/gravity residual bias, missing stop/zero-velocity handling, magnetic heading instability and vibration, and stale GNSS initialization. These are diagnostic hypotheses, not reference-tuned conclusions.

### Artifacts and tests

`results/raw_dr/io_vnbd/s1/` contains `summary.csv`, `summary.json`, `run_manifest.json`, separate prediction/evaluation CSVs and metrics JSON for five scenarios, twenty per-scenario plots, and three master plots. The manifest records the Phase 2 parent commit, Python executable/version, algorithm, equations/conventions, source hashes, timestamp, and artifact paths.

Thirteen Phase 3 tests cover stationary, constant-velocity, constant-acceleration and irregular-time integration; identity and 90-degree orientation; explicit GNSS leakage rejection; reference-free estimator API; determinism; invalid timing; real S1 smoke execution; future-GNSS rejection; and relative-versus-absolute evaluation. All 24 earlier tests also pass, for 37 total and zero failures.

## M4-001 - Calibrated motion-aware classical dead reckoning

Date: 2026-08-31
Phase: 4
Status: Passed

### Environment, baseline, and leakage boundary

Execution used `C:\Users\Prajwal\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`, Python 3.12.13, from parent commit `1f8644e1feb989d215a97473bebd4d9243becba9`. Before Phase 4 edits, the complete 37-test suite passed and `S1_60_STOP_GO` reproduced 327.185498 m final relative error / 124.502678% drift exactly.

`build_phase4_calibration` receives only the Phase 2 sensor frame plus phone-GNSS observations strictly earlier than blackout. It rejects future rows and evaluation-reference columns. `integrate_calibrated_dead_reckoning` receives only the completed calibration and GNSS-free blackout sensor rows; it has no VBOX/reference parameter and rejects phone-GNSS or reference fields. `evaluate_raw_dr_prediction` receives VBOX only after prediction. No VBOX metric was used to choose a parameter.

### Orientation investigation

The bundled IO-VNBD paper states that AndroSensor recorded the phone, depicts mounted +X in the direction of travel, and supplies per-axis gravity for acceleration correction. It does not specify the application's orientation/gyro remapping. Official Android documentation defines the standard device-to-ENU rotation and orientation extraction, including azimuth about -Z and pitch/roll conventions: [SensorManager](https://developer.android.com/reference/kotlin/android/hardware/SensorManager), [SensorEvent](https://developer.android.com/reference/android/hardware/SensorEvent), and the [AOSP SensorManager source](https://android.googlesource.com/platform/frameworks/base/+/master/core/java/android/hardware/SensorManager.java).

S1 contradicts a direct application of that standard: measured gravity remains nearly device +Z, with 0.024-0.171 degrees median tilt, but Phase 3 Euler tilt is 95.167-99.289 degrees and the gravity/Euler disagreement is similar. Strictly pre-blackout phone-GNSS comparisons also show exported gyroscope Y with negative sign tracks course changes: fitted scale is approximately -0.75 to -0.95 and correlation is -0.847 to -1.000 in standard calibration windows. This is evidence of an S1/AndroSensor export remapping, not a universal Android axis claim.

Phase 4 uses gravity-normalized Up, projects documented device +X into the horizontal plane as Forward, defines Left as `Up x Forward`, and maps vehicle acceleration into local ENU from course. Exported pitch/roll are diagnostic only. A robust circular mean of distinct moving pre-blackout phone-GNSS `course - exported azimuth` estimates mounting yaw. A 60-second window, 5 m/s moving threshold, minimum three anchors, and maximum 25-degree circular dispersion are fixed. Insufficient evidence falls back to the latest distinct phone course/azimuth anchor and propagates it to blackout start using runtime azimuth change.

### Conditioning, heading, and motion logic

- Linear acceleration is `accelerometer - gravity`, projected into gravity-derived Forward/Left/Up.
- Accelerometer and gyro bias use the robust median of causally confirmed pre-blackout stationary samples only. At least 20 samples and conservative magnitude limits are required; otherwise bias is exactly zero. Only the judge window supported a reliable estimate.
- Forward/left acceleration uses a first-order causal IIR at 1 Hz with `alpha = 1 - exp(-2*pi*fc*dt)`. No future sample or zero-phase pass is used.
- Course propagates with configured `-gyroscope_y`; the pre-blackout phone-course regression is recorded as a diagnostic rather than used to tune against VBOX.
- V5 slowly corrects gyro course toward calibrated exported azimuth with a 10-second time constant only when magnetic magnitude is 25-65 microtesla, magnitude change is at most 12 microtesla/s, azimuth rate is at most 90 degrees/s, and heading innovation is at most 45 degrees.
- A 1-second motion window enters stationary below 0.35 m/s² horizontal RMS and 0.04 rad/s gyro RMS after 2 seconds persistence. It exits above 0.60 m/s² or 0.08 rad/s after 0.5 seconds. Gravity must remain within 0.15 m/s² of standard gravity.
- ZUPT sets horizontal velocity to zero and holds position only in `LIKELY_STATIONARY`. V4/V5 additionally project moving velocity onto the estimated vehicle-forward axis, a ground-vehicle non-holonomic constraint; there is no generic velocity damping.

### Frozen ablation results (drift %)

| Variant | 10 s | 30 s | 60 s | 120 s | Judge 45 s |
|---|---:|---:|---:|---:|---:|
| V0 Raw Phase 3 | 8.306 | 67.337 | 124.503 | 138.004 | 100.592 |
| V1 Orientation | 38.185 | 254.872 | 424.128 | 146.213 | 112.052 |
| V2 Conditioned | 38.229 | 257.672 | 414.484 | 149.171 | 108.364 |
| V3 Heading stabilized | 38.389 | 199.774 | 447.432 | 147.685 | 8.119 |
| V4 Motion aware | 21.383 | 60.161 | 82.911 | 55.796 | 61.741 |
| V5 Combined | 19.991 | 60.868 | 83.865 | 75.227 | 61.294 |

V5 improves the 30-, 60-, and 120-second standards by 9.607%, 32.640%, and 45.489% in final error, respectively, but regresses the 10-second case by 140.683%. Standard median drift decreases from 95.920% to 68.048% (29.058% relative). The custom 45-second run decreases from 228.020 m / 100.592% to 138.941 m / 61.294%. V4 is better than V5 in three standard scenarios, showing that the frozen magnetic/orientation correction is not consistently beneficial; this negative evidence is retained rather than retuned against VBOX.

### Artifacts, performance, and tests

`results/phase4/io_vnbd/s1/` contains the complete summary, full ablation, sensor diagnostics, calibration records, 30 predictions, 30 evaluation time series, 32 plots, judge summary, and reproducibility manifest. Source hashes remained unchanged. The O(n), causal estimator processed approximately 8,998 samples/s on the development machine versus 10 Hz input.

Twenty-two new tests cover gravity attitude, circular statistics/wraparound, synthetic mounting calibration, gyro integration, causal/constant filtering, stationary positive/moving/hysteresis behavior, ZUPT gating, reference-free execution, explicit phone-GNSS/reference leakage rejection, future-data rejection, irregular timing, determinism, exact raw regression, and real S1 Phase 4 smoke execution. All 37 earlier tests pass, for 59 total and zero failures.

### Remaining failure modes and Phase 5 gate

Ranked limitations are: residual acceleration/initial-speed error; direct exported orientation unreliability; inconsistent benefit from magnetic correction; stale phone-GNSS solutions (44 seconds in the judge case); lack of uncertainty propagation; and S1-specific export/mount evidence that must not be generalized to arbitrary phones. The classical prior is finite, causal, deterministic, and reference-isolated with no unresolved sign/order bug inside its declared S1 convention. Phase 5 status is **READY**, but Phase 5 requires explicit user instruction and must retain these ablations and leakage controls.

## M5-001 - Hybrid EKF and ML-assisted dead reckoning

Date: 2026-09-01
Phase: 5
Status: Passed

### Freeze protocol and isolation

Execution used the project-local `.venv\Scripts\python.exe`, Python 3.12.10, from parent commit `1461f6404cef10f59d989db575feb0a6fa37508d`. The unqualified `python` command remained the obsolete MGLTools Python and was not used. Before edits, all 59 Phase 1-4 tests passed.

The split was fixed before evaluation. Each named blackout was quarantined from `start - 120 seconds` through `end + 60 seconds`: 10 s `[200,390)`, 30 s `[4435,4645)`, 60 s `[4095,4335)`, 120 s `[3375,3675)`, judge 45 s `[4730,4955)`, and the preselected surprise 75 s `[2880,3135)`. Seven time-contiguous training blocks and three disjoint validation blocks contain no quarantine overlap. Sixty-second development outages are initialized independently within blocks so training resembles deployment horizons without crossing split boundaries.

VBOX speed was attached only after each classical development sequence completed and was used as the offline residual label. The runtime estimator accepts no `EvaluationReference`, rejects phone-GNSS/reference columns, and uses only GNSS-free phone sensors, causal calibration, frozen config, and the checkpoint. Benchmark execution occurred only after the checkpoint/config hashes were written to `frozen_configuration.json`; no parameter was changed afterward.

### Model and validation

Training-only scaling used 24,395 feature rows. The ten inputs are conditioned forward/lateral acceleration, gyro course rate, gyro magnitude, gravity magnitude, magnetic magnitude, motion acceleration/gyro RMS, likely-stationary flag, and causal classical speed. The causal window is 20 steps / approximately 2 seconds, with no location, scenario ID, absolute route time, future sample, or VBOX input.

The one-layer 32-unit GRU predicts a bounded ±12 m/s residual and has 4,257 parameters. Seed 26168 controls Python, NumPy, and PyTorch. CPU Adam/Huber training produced 11,818 training and 3,489 validation windows; early stopping retained epoch 14 after 12.790 seconds. The 21,649-byte checkpoint reduced validation speed MAE 12.226 -> 6.814 m/s, RMSE 18.756 -> 12.635 m/s, and P95 absolute error 42.541 -> 30.552 m/s. Validation residual variance 128.782 m²/s² became the frozen ML measurement R.

### EKF

The state is `[east, north, speed, yaw, residual acceleration bias, residual gyro bias]`. The planar model uses measured `dt`, Phase 4 conditioned acceleration and gyro course, explicit acceleration/yaw/bias random-walk Q, nonnegative vehicle speed, Joseph-form scalar updates, covariance symmetrization, and finite/nonnegative checks. Stationary speed, wrapped heading, and ML speed measurement models use normalized-innovation-squared gates. Heading update is implemented but frozen off because Phase 4 magnetic correction was inconsistent. Training-range exceedance inflates ML R or skips the update. Reported uncertainty is `sqrt(Pxx + Pyy)` and is not claimed as a calibrated confidence radius.

### Held-out results

| Scenario | Distance m | Raw drift % | P4 V4 % | P4 V5 % | E1 EKF % | H1 Hybrid % | H1 final m | Final sigma m |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `S1_10_STEADY` | 154.156 | 8.306 | 21.383 | 19.991 | 21.388 | 22.655 | 34.924 | 48.427 |
| `S1_30_TURNING` | 200.925 | 67.337 | 60.161 | 60.868 | 23.615 | 18.571 | 37.313 | 44.099 |
| `S1_60_STOP_GO` | 262.794 | 124.503 | 82.911 | 83.865 | 36.182 | 28.232 | 74.192 | 162.372 |
| `S1_120_HIGHER_SPEED` | 1706.385 | 138.004 | 55.796 | 75.227 | 24.402 | 38.480 | 656.622 | 2277.729 |
| `S1_45_JUDGE` | 226.679 | 100.592 | 61.741 | 61.294 | 52.263 | 52.259 | 118.461 | 141.194 |
| `S1_PHASE5_SURPRISE` | 620.844 | 131.290 | 10.508 | 70.988 | 14.177 | 3.855 | 23.932 | 451.300 |

Standard median drift is 95.920% Raw, 57.979% Phase 4 V4, 68.048% Phase 4 V5, 24.009% E1, and 25.444% H1. H1 improves every difficult named case against the best Phase 4 variant, but it regresses the 10-second raw/P4 result and is worse than E1 on 10 and 120 seconds. The surprise holdout is the only sub-10% Phase 5 result and is not treated as proof of generalization. These outcomes were not used for retuning.

### Artifacts, performance, and validation

`models/phase5/io_vnbd_s1/` contains the checkpoint, training-only scaler, config/metrics, and model card. `results/phase5/io_vnbd/s1/` contains the split/freeze/run manifests, training history and validation trace, EKF/hybrid/ablation tables, six scenario result/time-series bundles, and 33 plots. The complete hybrid pipeline measured 1,528.7 samples/s, ML inference 1,536.2 windows/s (0.651 ms average), and E1 2,137.2 samples/s versus 10 Hz input. Original smartphone and VBOX reference SHA-256 hashes matched before/after execution.

Thirty-two new tests cover EKF kinematics, irregular `dt`, covariance/uncertainty, Joseph updates, wraparound, gating, determinism, causal windows, split/quarantine isolation, training-only scaling, model/checkpoint determinism, VBOX/scenario exclusion, OOD behavior, stationary updates, reference-free hybrid execution, future-GNSS rejection, S1 smoke execution, and saved-result reproduction. All 59 earlier tests pass, for 91 total and zero failures. Plots were visually inspected.

### Phase 6 gate

Phase 5 is ready for probabilistic map matching. Remaining limitations are single-journey training, material validation speed error, stale phone-GNSS initialization, uncalibrated covariance scale, large 120-second uncertainty, and heading errors that speed ML cannot repair. No map matching, road graph, GNSS reacquisition, Android application, or secondary dataset work was performed.

## M6-001 - Offline probabilistic multi-hypothesis map matching

Date: 2026-09-01
Phase: 6
Status: Passed

### Baseline, map, and freeze

Execution used `C:\Users\Prajwal\Desktop\SIH26168-IDR\.venv\Scripts\python.exe`, Python 3.12.10, from parent commit `39b50c109552cc35e4c2b75a3e65f29fa4587348`. All 91 Phase 1-5 tests passed before edits. No new Python dependency was installed.

A single OpenStreetMap/Overpass download built `data/map_cache/io_vnbd_s1/road_graph.json.gz`. The fixed bounds are 52.3944–52.4239 N, -1.6074–-1.5013 E, selected from the whole S1 smartphone-GNSS envelope plus buffer without VBOX. The 1,044,506-byte deterministic gzip stores 23,103 nodes and 43,488 directed vehicle-road edges; metadata records OSM timestamp, query, attribution, classes, counts, checksum, local-coordinate convention, and offline-runtime policy.

Phase 6 development used only `[1120,1180)`, `[2020,2080)`, and `[4000,4060)`, all inside the Phase 5 validation blocks and outside every quarantine interval. Three profiles compared top K/beam, radius scaling/cap, distance/heading/transition scales, and ambiguity gap for both EKF and Hybrid priors. Hybrid mean development drift was 27.614% versus EKF 110.235%. Hybrid drift tied across profiles; `WIDE_CONTINUITY` had the lowest Hybrid mean RMSE (73.487 m) and was frozen with Hybrid before any held-out run. No setting changed afterward.

### Runtime algorithm and isolation

The runtime matcher accepts only Phase 5 elapsed time, east/north, speed, yaw, horizontal sigma, and the static road cache. It rejects phone-GNSS or reference-labelled fields and has no route, destination, scenario truth, VBOX, or `EvaluationReference` argument. Pre-blackout phone GNSS supplies the unchanged Phase 5 local-frame origin and first state. VBOX is passed only to `evaluate_map_match` after road matching completes.

Candidate search uses a 75 m uniform grid and `clamp(20 + 2*sigma, 15, 220)` m radius. Exact polyline projection supplies distance, fraction, and segment-local clockwise-from-North bearing. Distance, circular heading, one-way, cautious class/speed, network-distance, turn, and edge-switch scores accumulate in log space. Limited directed Dijkstra measures only candidate-to-candidate road travel. Top K and beam width are 10. Probability-gap/normalized-entropy ambiguity is explicit. Missing candidates, probability below 0.12, or correction above 120 m returns the Phase 5 point and retries later.

### Held-out outcome

| Scenario | Distance m | Raw % | Phase 4 best % | EKF % | Hybrid % | Hybrid nearest % | ProbMap EKF % | ProbMap Hybrid/final % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `S1_10_STEADY` | 154.156 | 8.306 | 19.991 | 21.388 | 22.655 | 14.471 | 5.790 | 16.533 |
| `S1_30_TURNING` | 200.925 | 67.337 | 60.161 | 23.615 | 18.571 | 17.644 | 21.995 | 21.995 |
| `S1_60_STOP_GO` | 262.794 | 124.503 | 82.911 | 36.182 | 28.232 | 33.286 | 35.640 | 27.387 |
| `S1_120_HIGHER_SPEED` | 1706.385 | 138.004 | 55.796 | 24.402 | 38.480 | 38.034 | 25.455 | 38.034 |
| `S1_45_JUDGE` | 226.679 | 100.592 | 61.294 | 52.263 | 52.259 | 50.285 | 53.798 | 53.798 |
| `S1_PHASE5_SURPRISE` | 620.844 | 131.290 | 10.508 | 14.177 | 3.855 | 2.987 | 12.408 | 3.887 |

The fixed final improves the best Phase 5 prior in two scenarios and regresses four. One of six is below 10%. Median drift changes from 22.895% best-Phase-5 to 24.691% Phase 6. Results were not used to retune. Nearest road beats the probabilistic method on reference error in four S1 cases, ties on 120 seconds, and loses on stop-go; this negative evidence is retained. Synthetic parallel-road and left-junction tests verify that temporal heading/topology history behaves correctly even though the recorded S1 prior can still select a wrong connected branch.

Weighted final diagnostics are 9.96 candidates, 21.51% ambiguity, 0% no-candidate, 27.72 m mean correction, 92.26 m maximum correction, and 93 road/hypothesis switches. Throughput is 43.37 candidate samples/s, 41.68 probabilistic matches/s, and 34.53 Phase5+Phase6 samples/s. Source smartphone/VBOX hashes matched before and after.

### Artifacts and tests

`results/phase6/io_vnbd/s1/` contains development comparisons, held-out summaries and time series, full ablation, candidate/hypothesis/correction diagnostics, map/split/run manifests, and 21 plots. `results/phase6/PHASE6_JUDGE_SUMMARY.md` explains the system and limitations for judges. Forty new tests cover the requested coordinate, road geometry, candidates, heading, one-way, transitions, hypotheses, ambiguity, fallback, leakage, synthetic parallel/junction/turn, and S1 smoke cases. All 91 earlier tests pass, for 131 total and zero failures.

Phase 7 status is **READY** for GNSS reacquisition engineering only. No Phase 7, Android, destination routing, or secondary-dataset implementation was started.

## M7-001 - Causal GNSS loss detection and smooth reacquisition

Date: 2026-09-01
Phase: 7
Status: Passed

Baseline was locked at `da45078a82f2b518d9e7b74289435b263e974dec`; 131/131 tests passed before Phase 7. Existing Phase 4/5/6 manual-reproduction modifications were preserved and excluded from Phase 7 staging.

S1 logs rows near 10 Hz, but navigation position/speed/course changes occur at roughly a 9-second median cadence. The tracker therefore accepts only complete, range-valid phone GNSS and labels a solution fresh when position changes by more than 0.5 m, speed by more than 0.25 m/s, wrapped course by more than 2 degrees, or altitude by more than 0.5 m relative to the last genuinely fresh solution. Accuracy and satellite text validate/describe a fix but do not manufacture position freshness.

Three development-only blackout/recovery spans, `[1070,1210)`, `[1940,2090)`, and `[3790,3930)`, avoid all held-out quarantines. A small comparison selected `FAST_TWO_FIX` before held-out execution: two mutually consistent fresh fixes; 15-second stale timeout; 20-second verification gap; uncertainty gate `max(25 m, 3*hypot(IDR sigma, GNSS accuracy))`; three-second trust ramp/time constant; 0.15-0.85 gain; and 10 m/s maximum correction rate. The innovation gate is diagnostic, not a permanent hard rejection, because legitimate long-outage drift can be large.

The runtime accepts only `RuntimeDataset`, current observation, Phase 5/6 output, static map, and frozen configuration. It exposes no VBOX/reference, future GNSS/IMU, route, destination, scenario ID, or benchmark truth. `evaluate_phase7_runtime` is the only VBOX boundary and runs after all runtime outputs are complete.

| Scenario | Fresh delay s | B1 snap m | P7 max step m | Recovery s | Return active s | Post RMSE m | P95 m | Final m |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| S1_10_STEADY | 0.100 | 13.453 | 1.030 | 26.401 | 36.400 | 57.827 | 148.631 | 7.749 |
| S1_30_TURNING | 0.000 | 88.491 | 1.030 | 8.301 | 16.300 | 103.073 | 155.209 | 80.261 |
| S1_60_STOP_GO | 0.001 | 176.087 | 1.040 | 33.898 | 80.899 | 107.639 | 209.572 | 27.562 |
| S1_120_HIGHER_SPEED | 0.000 | 563.128 | 1.050 | 77.400 | 88.400 | 324.712 | 644.336 | 69.597 |
| S1_45_JUDGE | 0.100 | 101.450 | 1.030 | 33.700 | 40.700 | 108.661 | 151.025 | 82.952 |
| S1_PHASE5_SURPRISE | 0.100 | 87.224 | 1.010 | 12.799 | 14.799 | 28.276 | 53.445 | 36.581 |

All frozen Phase 6 drift values reproduced exactly within `1e-9` percentage points. Warm representative processing excluded loading, localization/index construction, VBOX, output, and plots: conservative Phase5+Phase6+Phase7 was 51.83 samples/s / 19.29 ms per sample; incremental Phase 7 was 0.075 ms average, 0.073 P50, 0.135 P95, and 0.218 P99. Source hashes remained unchanged. Twenty-six new tests plus 131 earlier tests passed (157 total). Phase 7 addresses loss/recovery continuity and does not claim to eliminate accumulated inertial/map error.

## M8-001 - Cross-dataset zero-shot generalization

Date: 2026-09-01
Phase: 8
Status: Passed

Baseline was locked at `93ddc6b072917db23c1feb7e505e83943d2e9d36`; the manually confirmed Phase 7 state and 157-test suite were preserved. The audit found Smartphone Decimeter suitable for core evaluation, WHU reference-only, MoRPI partially compatible but missing magnetometer/GNSS/reference, and PPC/GREAT unusable locally because sequence payloads were absent. Only the strongest scientifically compatible source was executed.

Before target reference evaluation, four runtime-signal windows were frozen: Pixel 4 XL/Mountain View at 240 s for 10 s, 968 s for 30 s, and 1800 s for 60 s; Pixel 5/Los Angeles at 1577 s for 30 s. Selection used only WLS displacement speed, gyro activity, session/device diversity, and sufficient prehistory. The 10-second window later proved stationary in reference and was not replaced.

Runtime device IMU was bias-corrected using source-provided Android uncalibrated-sensor bias columns and causally aggregated from ~52.63/100 Hz to right-closed 10 Hz bins. A two-second causal accelerometer low-pass supplied gravity. A fixed horizontal motion axis came from the principal horizontal acceleration direction in the strictly pre-blackout 60-second runtime window; its sign ambiguity was resolved by the existing runtime WLS-course/magnetic-heading alignment. WLS ECEF converted to WGS84 geodetic coordinates, and speed/course used a five-second past-only displacement. Target `ground_truth.csv` was loaded only after all runtime predictions completed.

Moving-window median drift was 120.262% Raw, 56.633% Phase 4 V5, 64.151% EKF, and 40.866% Hybrid. EKF improved raw twice in three moving windows. Hybrid improved EKF once and degraded it twice; magnetic magnitude was the dominant S1-scaler shift, and the unchanged hard-OOD gate skipped 64.286% of attempted ML updates in the MTV dynamic window and all attempted updates in the stationary window. This is classified **MODERATE GENERALIZATION** with inconsistent ML transfer. The S1 road graph was not reused outside its geography, and Phase 7 was not forced because WLS lacks a defensible per-fix accuracy input.

Warm Hybrid processing on `SDC_MTV_60_HIGHER_SPEED` was 1,394.6 samples/s and 0.717 ms/sample for in-memory conditioning + EKF + frozen GRU/OOD processing. Loading, adapter/calibration, evaluator/reference, output, and plots were timed separately/excluded. P95 was not added because the frozen batch estimator lacks per-sample instrumentation. Consumed source-file hashes matched before/after; model/scaler/Phase 6/Phase 7 hashes matched the frozen manifest. Twenty-three Phase 8 test cases were added; all 157 earlier tests passed, for 180 total and zero failures.

## M9-001 - Android sensor logger and deterministic desktop replay

Date: 2026-09-01
Phase: 9
Status: Passed on host; physical-device verification pending

Baseline was locked at `7dd4a1db840687589d079d9b81f945a659d94d93`; known earlier manual-reproduction modifications remained untouched and excluded from Phase 9 staging. The existing Android SDK 36.1, Android Gradle Plugin 9.2.1, Gradle 9.4.1, and JDK 21.0.8 built the debug APK offline. No large toolchain or new Python dependency was installed.

The Android service records `TYPE_ACCELEROMETER`, `TYPE_GYROSCOPE`, `TYPE_MAGNETIC_FIELD`, `TYPE_GRAVITY`, `TYPE_ROTATION_VECTOR`, and `LocationManager.GPS_PROVIDER`. Native sensors are requested at 20,000 microseconds but observed rates come from timestamps. Sensor events, location fixes, and 10 Hz snapshots share elapsed-realtime monotonic nanoseconds; wall UTC is diagnostic only. A bounded per-sensor queue rejects non-increasing input and a snapshot selects only the latest sample at or before its own timestamp.

Physical GNSS and runtime GNSS are separate domains. Simulated blackout returns a null runtime fix with `SIMULATED_BLACKOUT`, while a raw physical callback can be retained only in `gnss_raw.csv` with `masked_from_runtime=true`. Runtime latitude, longitude, altitude, speed, bearing, provider, and quality columns are empty. Kotlin and Python tests enforce this. All data stays app-private unless the user explicitly exports a ZIP through Storage Access Framework.

The deterministic synthetic fixture contains 1,000 raw sensor callbacks (five sensors at 50 Hz), 40 causal 10 Hz samples, five physical GPS callbacks, a stale interval, a one-second blackout, a masked physical callback inside that blackout, and recovery. The Python reader validates schema, units, clock agreement, ordering, availability, states, and leakage; its canonical adapter consumes only `runtime_10hz.csv`. Replay is chronological, deterministic in content, and exposes health/OOD fields without enabling ML (`NOT_EVALUATED`).

Ten Kotlin/JVM tests and debug APK assembly passed. Twenty-four new Python tests plus all 180 previous tests passed (204 total). Frozen Phase 5/6/7 hashes matched. No APK was installed and no physical sensor, background endurance, battery/CPU, export-on-device, or real-road accuracy result is claimed. Phase 10 implementation was not started.

## M9.1-001 - Android GNSS first-fix and observability hardening

Date: 2026-09-02
Phase: 9.1
Status: Passed; host tests and physical GNSS plumbing verified

Baseline was locked at `4077378369c7cd6fa209a594f3ef0ff4afcb7d25`. Existing manual-reproduction result changes and Android Studio-generated local files were preserved and excluded from staging. No Phase 5/6/7 behavior or configuration was changed, no model was trained, and Phase 10 was not started.

The motivating phone run verified all Android IMU sensors near 50 Hz, a 9.51 Hz normalized stream, the blackout state, export, desktop parsing, and replay. It produced zero `GPS_PROVIDER` callbacks, so its `NO_FIX`/blackout sequence was not evidence of real GNSS masking or recovery.

Schema v2 now starts in `WAITING_FOR_FIRST_FIX` and distinguishes it from `FRESH`, `STALE`, `INVALID`, `PROVIDER_DISABLED`, and `SIMULATED_BLACKOUT`. The service records physical callback count, true callback-arrival age, the last Android location monotonic timestamp, first valid fix timestamp, recording-relative time to first valid fix, `GnssStatus.Callback` availability, and nullable visible/used satellite counts. A blackout before first valid fix says `NO REAL FIX TO MASK` and writes `blackout_masks_real_fix=false`; after first fix it writes true while runtime GNSS remains fully hidden. Phase 9 schema-v1 exports remain readable without inventing satellite data.

The Android guide requires an outdoor/open-sky first-fix check before blackout and explains that a stationary phone is sufficient for GNSS plumbing. The offline Android command passed 16 Kotlin/JVM tests and assembled the debug APK; the complete Python regression passed 209 tests. A subsequent open-sky phone run measured approximately 50.0-50.2 Hz IMU and 9.6 Hz runtime output, reported 60 visible/5 used satellites, acquired its first fix in 19.17 s, and received four physical callbacks. During blackout, callback age remained approximately 0.50 s while runtime latitude, longitude, speed and bearing were unavailable and `blackout_masks_real_fix=true`. This verifies physical acquisition/masking plumbing, not real-road dead-reckoning accuracy.

## M10-001 - Standalone Android live IDR engine and navigation UI

Date: 2026-09-02
Phase: 10
Status: Passed on host; physical Phase 10 drive validation pending

Baseline was locked at `e039ec77ee02da15f7a314d3eaec37a539092650`. Existing dirty Phase 4/5/6 reproduction outputs, untracked reproduction directories, and Android Studio local files were preserved and excluded from Phase 10 staging. No frozen estimator configuration was edited and no ML training occurred.

`SensorLoggingService` now passes each Phase 9.1 causal `LiveIdrSample` to a native `IdrEngine` on the snapshot thread. Runtime conditioning subtracts Android gravity, rotates by the current quaternion, projects to a causally learned vehicle frame, filters with a 0.30 s time constant, and detects stationary windows. A full-covariance six-state EKF propagates east/north/speed/yaw/accelerometer-bias/gyroscope-bias and supports fresh-GNSS, rotation-vector, zero-speed and OOD-gated ML measurements. Local equirectangular coordinates use a per-session first-fix origin and mean Earth radius without asserting an unsupported CRS.

The frozen Phase 5 checkpoint hash remains `fa2169781f9e499dd87fdd00038a3b4a1326181b31938cec237a7802ae0bb4ec`. Its 4,257 float32 parameters, ten-feature scaler/bounds, 20-step window and five-step stride were exported into pure Kotlin GRU equations. Three Python golden windows pass Kotlin residual parity within `1e-4` m/s and OOD parity within `1e-5`. Soft OOD uses four times the accepted measurement variance between exceedance 0.5 and 3.0; hard OOD rejects it. A development defect that re-applied the last residual on all intermediate samples was caught by the synthetic demo and fixed so the update is applied only on a new five-step inference.

Runtime GNSS is null during Phase 9.1 simulated blackout and `IdrEngine` independently rejects any supplied fix when the blackout flag is true. Tests include a deliberately malformed blackout sample carrying GNSS and prove no position teleport/leakage. The engine distinguishes waiting, calibrating, GNSS active/degraded, IDR active, verifying and bounded recovery. Two distinct fresh fixes are required; correction is capped at 0.5 m for a normal 0.1 s sample (5 m/s).

The wholly synthetic 270-sample demo exercises six seconds active GNSS, ten seconds complete loss, and reacquisition through `GNSS_VERIFYING`/`GNSS_RECOVERING` back to `GNSS_ACTIVE`. It propagates 59.991 m during blackout. A separate moving fixture propagated 23.501 m over 2.9 seconds while covariance sigma grew 1.153 -> 2.687 m. The stationary fixture ended at 0.0 m/s and 4.39e-8 m displacement. Recovery started at 8.338 m innovation, limited correction to 0.5 m/sample, and ended 0.080 m from the returned fix.

The app main screen was replaced with LIVE, clearly labelled `DEMO REPLAY • SYNTHETIC • NOT LIVE`, and DIAGNOSTICS tabs. A custom offline ENU canvas renders trajectory state, current heading, origin, north, scale and covariance uncertainty; no road-map/route claim is made. Root content applies left/top/right/bottom system insets. Phase 9.1 sensor/GNSS diagnostics and export remain available. Session logging adds `idr_output.csv` schema v1 without changing the existing raw/runtime files.

An isolated warm engine-only JVM run measured approximately 3,471 samples/s, 0.288 ms/sample average and 0.899 ms P95, excluding Android sensors, UI, logging, startup and power/thermal effects. Fourteen new Kotlin tests plus all 16 previous tests passed (30 total); three new Python tests plus all 209 previous tests passed (212 total). Offline debug APK assembly passed. No emulator/physical Phase 10 UI or drive test was performed, no private recording was committed, and Phase 11 was not started.

## M11-001 - Android real-world hardening and field-validation harness

Date: 2026-09-03
Phase: 11
Status: Passed on host; physical road evidence pending

Baseline was locked at `0fba06828983714e71afc6516cd67131ed54aaf9`. Pre-existing Phase 4-8 reproduction changes, untracked reproduction directories, and Android Studio/Gradle local files were preserved and excluded. The Phase 5 GRU was not retrained or refit; its checkpoint remains `fa2169781f9e499dd87fdd00038a3b4a1326181b31938cec237a7802ae0bb4ec`.

The stationary-phone failure was traced to initial `MOVING` state and propagation using an unverified vehicle yaw. The fix introduces `INITIALIZING`, a 20-sample fixed-threshold stationary detector with five-sample exit hysteresis, and `CALIBRATION_REQUIRED`. If GNSS is lost before vehicle alignment, position and speed are held while unknown-direction covariance grows. Realistic-noise 30/60/120-second fixtures ended at 0.000112/0.000154/0.000158 m with zero speed, maximum below 0.000286 m, 100% stationary classification after initialization, and growing sigma.

GNSS diagnostics now separate physical NONE/FRESH/STALE, runtime AVAILABLE/MASKED/UNAVAILABLE, session-ever acquisition, and currently fresh masking. An automatic controller implements warm-up, readiness wait, baseline, 10/30/60/120-second blackout, recovery, completion and safe cancellation. Session metadata/events add field ID/preset/mount, engine/ML timing/counts, battery/temperature/thermal, foreground state and logger errors.

The offline validator reads an arbitrary external Android session, verifies exact runtime/IDR sequence alignment, quality-gates physical phone GNSS, applies evaluator-only interpolation, and reports complete blackout, error, drift, recovery, uncertainty/sigma, ML/OOD and reference-quality metrics. Optional CSV/GPX reference is supported. Outputs default beside the private session. The existing Vivo export was inspected read-only and classified not evaluable: no estimator output and zero usable physical reference fixes.

The Android UI is now a dark navigation-first product surface with a robust follow/auto-fit ENU viewport, calibration progress, prominent state/uncertainty/speed/DR/AI telemetry, automatic field controls, synthetic demo timeline and evaluator-only comparison overlays, and structured SENSORS/GNSS/ENGINE/AI/SESSION/SYSTEM diagnostics. Text accompanies every state color and system insets remain four-sided.

A compact public IO-VNBD S1 Kotlin fixture preserves runtime/evaluator separation and verifies that a blackout before adequate alignment safely holds position. It ends `CALIBRATION_REQUIRED`; the evaluator-only final discrepancy is 70.504 m and is retained as a safety/domain observation, not an accuracy claim. No uncertainty scale was fitted without new valid road reference data; sigma remains engineering covariance rather than a calibrated 95% interval.

Warm engine-only JVM processing was 11,545 samples/s, 0.0866 ms average and 0.185 ms P95. All 44 Kotlin/JVM tests and 217 Python tests passed. No new physical drive, endurance measurement, survey-grade reference, private session commit, or universal <10% drift claim is made.

## M12-001 - Final competition release

Date: 2026-09-03
Phase: 12
Status: Passed on host; immutable competition release

Baseline `a0eadece9b34e2a7d8b19ad8edb410642c9d0402` was verified before edits. Pre-existing Phase 4-8 reproduction changes, reproduction directories, and Android Studio/Gradle local files were preserved and excluded. No EKF, alignment, stationary, recovery, GRU, scaler or OOD setting changed; the checkpoint SHA-256 remains `fa2169781f9e499dd87fdd00038a3b4a1326181b31938cec237a7802ae0bb4ec`.

The final Android release uses `SIH26168 • IDR` identity and version 1.0.0. LIVE retains the proven engine path and adds exact geographic coordinates when available, human tunnel terminology, a clearer narrow-screen header, explicit map status, and expanded SYSTEM/SENSORS/GNSS/LOCALIZATION/AI/FIELD TEST/SESSION/PERFORMANCE/MAP diagnostics. Original vector launcher/splash artwork was added. Activity page/demo/preset/mount state is retained across recreation and demo execution pauses when the Activity leaves the foreground.

A deliberately narrow `MapProvider` returns presentation metadata only. `EngineMarkerPolicy` accepts only `NavigationSnapshot`, so no map SDK/provider can inject position. The shipped provider is a guaranteed credential-free local ENU fallback labelled `MAP OFFLINE • LOCAL VIEW`. No internet permission, Google key, Google SDK, network provider or proprietary scraping was added. Phase 6 road matching remains research-only and is not forced into LIVE.

The existing 27-second synthetic engine demo remains the fast judge path. A separate evaluator-only public replay down-samples the already frozen IO-VNBD `S1_60_STOP_GO` output and presents reference, Raw DR and Intelligent IDR tracks. Its labelled evidence is 60 seconds, 262.794 m reference travel, 327.185 m Raw final error, and 74.192 m / 28.232% Hybrid drift. Reference data is never passed to `IdrEngine`.

Five Kotlin tests were added for map fallback/location isolation, public-replay determinism/reference separation, and state-label consistency. Six Python tests were added for frozen hash, release assets, secret scan, private-data exclusion, build/network identity, lifecycle source checks and API isolation (the prior count-to-total increase is six because Phase 12 is one six-test module). Final totals are 49 Kotlin and 223 Python, all passing. Offline `testDebugUnitTest assembleDebug` succeeded. The APK is 1,139,587 bytes with SHA-256 `1c619fb2110ebf6d13d2cb4e5c54b86f3cba768e6e743d02bc24eeb06cf1c73d` at the final pre-commit build.

No ADB device was connected, so no new Phase 12 visual screenshot or logcat claim is made. Source/layout review covered four-sided insets, narrow-header text, scrollable screens, text-plus-color state semantics, local fallback, hidden public controls, and diagnostics consistency. The final verifier records the immutable commit/tag, hashes, test totals and bundle after commit. Remaining work is physical only; no Phase 13 is started.

## RELEASE-001 - NavGhost final product polish

Date: 2026-09-03
Status: Passed on host

Baseline `84fb5614511c73524087dcebe04ed710309991a2` and fallback tag `sih26168-final` were verified before edits. The frozen engine, estimator settings, dataset results and GRU checkpoint were not changed. Existing unrelated Phase 4-8 reproduction outputs and Android Studio files were left untouched and excluded from the release commit.

The visible application is now **NavGhost — Navigation Beyond GNSS** 1.1.0 while retaining package `org.sih26168.idrlogger`. The launcher, adaptive/monochrome icon, splash, foreground notification, header and About sheet use a consistent dark-navy/cyan compass-arrow identity. The About sheet credits Smart India Hackathon SIH26168 and the problem-statement organization ISRO / Department of Space while explicitly stating that this is not an ISRO-built or certified product. The external logo/icon/screenshot files described by the prompt were absent from its attachment directory, so the identity was implemented as repository-native Android vectors.

The official Google Maps SDK 20.0.0 is an optional, visual-only layer. A restricted developer key is read from ignored `android/local.properties`; its value was neither printed nor added to source. Google My Location and its button are disabled. The only marker input is `EngineMarkerPolicy.from(NavigationSnapshot)`. Missing configuration/services/network and load failure fall back to the local ENU renderer; the layer control also exposes LOCAL because the SDK offers no authentication-failure callback.

LIVE is map-dominant with an engine arrow, engineering-uncertainty halo, state-colored trajectory, speed/localization/AI/DR telemetry, calibration and field-test overlays, heading/north-up, gesture-aware follow/recenter and optional satellite view. DEMO adds a visible phase timeline and simultaneous Intelligent/Raw/reference comparison. SYSTEM adds a compact readiness summary and truthful map diagnostics. Permission explanation, local export, screen-awake scoping, haptics, page fades and private-storage behavior are preserved or improved.

Seven Kotlin tests were added for configured/missing/unavailable providers, API-shape isolation, coordinate projection, camera throttling, follow/recenter and heading/north-up behavior. Five Python tests were added for NavGhost identity, secure key wiring, no blue-dot/fused source, fallback controls and launcher/splash resources. All 49 earlier Kotlin and 223 earlier Python tests remain green: **56 Kotlin/JVM** and **228 Python** total. Offline APK assembly passes. The APK is 2,350,772 bytes with SHA-256 `b8a8dc573b4b3d105994815e3d87e4591c754542c2d8effcf3e93b4e24d8afc2`; the frozen GRU remains `fa2169781f9e499dd87fdd00038a3b4a1326181b31938cec237a7802ae0bb4ec`. No connected device/emulator was available for a new screenshot or live Google-tile check.
## TRUE3D-001 - MapLibre/OpenFreeMap navigation renderer

Date: 2026-09-10
Status: Passed on emulator; physical validation pending

Starting from protected v1.3 commit `82d516fd85989d13511336d14f478d477f2f833b`,
an isolated Gate A fixture loaded the OpenFreeMap Bright style and added a MapLibre
fill-extrusion layer over the real `building` vector source. Central Bengaluru
screens visibly showed roofs, vertical faces, occlusion, perspective depth, and
heading-dependent parallax; no satellite imagery or generated geometry was used.

Gate B connected only immutable `NavigationSnapshot` output to marker, travelled
history, state colors, camera, and estimator-radius uncertainty. No localization,
GNSS freshness, EKF, GRU, OOD, alignment, recovery, dataset, metric, or telemetry
behavior was changed. True 3D is default after style readiness; Google and local ENU
remain fallbacks. A bounded vector-load failure cannot stop the engine.

Focused JVM checks cover look-ahead, pitch, bearing wrap, stationary stability,
gesture/recenter, renderer failure selection, and exact uncertainty radius. The
Android screen test uses labelled non-live fixtures and verifies the true-3D camera
and lower marker framing. Physical Vivo driving and network/thermal checks remain
explicitly unverified.
