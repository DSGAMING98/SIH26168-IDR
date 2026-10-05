# NavGhost final performance table

Audit date: 2026-10-05. These are frozen IO-VNBD S1 **offline replay** numbers, not moving-phone measurements of the current APK. Position error is relative to the blackout starting position; the absolute global offset can be larger. Drift = final relative-position error / reference distance travelled. The synchronized VBOX stream is the offline reference, not survey-grade truth.

## Frozen source-domain blackout results

`Raw` = inertial DR; `EKF` = classical estimator; `Hybrid` = EKF plus safety-gated GRU; `Map` = Phase 6 research matcher applied to Hybrid output. **The Android app does not deploy the Map column.** RMSE, P95, maximum and sigma are Hybrid results. Sigma is covariance-derived engineering uncertainty, not a calibrated confidence interval. Recovery duration comes from a separate Phase 7 host replay.

| IO-VNBD S1 window | Duration | Reference distance | Raw final error | EKF final error | Hybrid final error | Research Map final error | Hybrid drift | Hybrid RMSE | Hybrid P95 | Hybrid max | Sigma start → end | Host recovery |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Steady | 10 s | 154.16 m | 12.80 m | 32.97 m | 34.92 m | 25.49 m | 22.655% | 19.52 m | 33.00 m | 34.92 m | 4.27 → 48.43 m | 26.40 s |
| Turning | 30 s | 200.92 m | 135.30 m | 47.45 m | 37.31 m | 44.19 m | 18.571% | 37.08 m | 57.21 m | 58.13 m | 4.26 → 44.10 m | 8.30 s |
| Stop/go | 60 s | 262.79 m | 327.19 m | 95.08 m | 74.19 m | 71.97 m | 28.232% | 54.16 m | 74.02 m | 74.19 m | 4.26 → 162.37 m | 33.90 s |
| Higher speed | 120 s | 1706.39 m | 2354.89 m | 416.39 m | 656.62 m | 649.00 m | 38.480% | 342.34 m | 620.43 m | 656.62 m | 4.26 → 2277.73 m | 77.40 s |
| Judge-style, supplementary | 45 s | 226.68 m | 228.02 m | 118.47 m | 118.46 m | 121.95 m | 52.259% | 60.96 m | 108.93 m | 118.46 m | 4.25 → 141.19 m | 33.70 s |
| Preselected surprise, supplementary | 75 s | 620.84 m | 815.11 m | 88.01 m | 23.93 m | 24.13 m | 3.855% | 56.93 m | 85.10 m | 88.36 m | 4.27 → 451.30 m | 12.80 s |

The four standard windows have median drift **25.44%**, mean **26.98%**, best **18.571%**, worst **38.480%**. **0/4 meet the under-10% target.** The separate 75-second surprise window passes but does not establish general performance. The 10-second raw baseline beats EKF/Hybrid; the 120-second EKF beats Hybrid. These counterexamples remain visible.

Sources: [Phase 5 summary CSV](phase5_summary.csv), [Phase 6 map comparison CSV](phase6_map_summary.csv), [Phase 7 recovery CSV](phase7_recovery_summary.csv), [individual replay outputs](../gnss_denied/scenarios/), [plots](../plots/).

An independent 60-second replay on 2026-10-05 reproduced **74.19228462027947 m Hybrid final error, 28.23211351129181% drift, 54.15801438775572 m RMSE and 74.02202317015441 m P95**. Timing from this one host replay varied and is not a phone latency result.

## Velocity model

Time-blocked IO-VNBD S1 validation: classical speed MAE **12.226 m/s**, RMSE **18.756 m/s**, P95 absolute error **42.541 m/s**, signed bias **+9.399 m/s**. ML-corrected speed MAE **6.814 m/s**, RMSE **12.635 m/s**, P95 **30.552 m/s**, signed bias **+5.560 m/s**. These are validation-window metrics, not cross-device performance. [Metrics JSON](velocity_validation_metrics.json).

Frozen model: one-layer 32-hidden-unit GRU, 10 features, 20 time steps at nominal 10 Hz, one bounded speed residual, 4,257 parameters, 21,649-byte checkpoint, best epoch 14, Huber loss, batch 128, learning rate 0.002. Training/validation windows: 11,818/3,489 from separated time blocks. SHA-256 `fa2169781f9e499dd87fdd00038a3b4a1326181b31938cec237a7802ae0bb4ec`. [Model card](../models/model_card.md), [training curve](../plots/training_curve.png).

## Cross-dataset zero-shot check

Only moving windows are included in drift comparison. The SDC steady 10-second window has **0 m reference distance**, so drift is undefined.

| Google Smartphone Decimeter 2022 window | Device | Duration | Distance | EKF final error / drift | Hybrid final error / drift | Verdict |
|---|---|---:|---:|---:|---:|---|
| Mountain View dynamic | Pixel 4 XL | 30 s | 337.24 m | 78.61 m / 23.31% | 137.82 m / 40.87% | Hybrid worse |
| Mountain View higher speed | Pixel 4 XL | 60 s | 1582.82 m | 1278.64 m / 80.78% | 1287.19 m / 81.32% | Hybrid worse |
| Los Angeles dynamic | Pixel 5 | 30 s | 495.94 m | 318.15 m / 64.15% | 136.49 m / 27.52% | Hybrid better |

Source: [cross-dataset summary](cross_dataset_summary.csv) and [Phase 8 methodology](../docs/phase8_cross_dataset_validation.md). WHU, MoRPI, PPC and GREAT are inventory-only or locally incompatible, not validated frozen-estimator datasets.

## Android, offline and device scope

| Measurement | Result | Scope |
|---|---:|---|
| Physical device | Vivo V2513, Android 16, app 2.4.0 | USB-connected; app launched indoors on 2026-10-05 |
| Current indoor GNSS | Waiting for a trusted fix | No outdoor first fix or moving route in this audit |
| Earlier physical native IMU | Approximately 50 Hz | Historical Phase 9.1 phone evidence; not remeasured today |
| Earlier normalized engine stream | Approximately 9.6 Hz | Historical Phase 9.1 phone evidence; current code targets 10 Hz |
| Earlier first fix | 19.17 s | Historical outdoor Phase 9.1 run; not a new result |
| Host JVM engine-only timing | 0.0866 ms average, 0.185 ms P95 | Historical warm Phase 11 microbenchmark; excludes sensors/UI/thermal |
| Current device engine processing average/P95 | NOT AVAILABLE | Engine was not running in a safe moving validation session |
| Current moving blackout / recovery accuracy | NOT AVAILABLE | No independently referenced road run this audit |
| Current battery/thermal impact | NOT AVAILABLE | Not measured |
| Current tests | 288 Python, 187 Kotlin | 2026-10-05; 0 failures |
| Android lint | Passed, 222 warnings, 0 errors | Mostly `SetTextI18n` warnings (174) |
| Keyless Google 3D build | Passed; `MAPS3D_CONFIGURED=false` | Local ENU fallback available |
| Configured Google 3D build | Passed; `MAPS3D_CONFIGURED=true` | Debug build; no new 3D field accuracy claim |

Android instrumentation tests were not run on the existing data-bearing phone because one UI test persists a test trip and changes a preference. This is an evidence gap, not a passed test. Private phone traces remain outside Git.

## Reproducible visual evidence

The [60 s trajectory comparison](../plots/s1_60_stop_go_trajectory_comparison.png), [position error](../plots/s1_60_stop_go_position_error.png), [speed comparison](../plots/s1_60_stop_go_speed_comparison.png), [uncertainty](../plots/s1_60_stop_go_uncertainty.png), [training curve](../plots/training_curve.png), [research map-matching before/after](../plots/map_matching_60s_before_after.png), [GNSS recovery timeline](../plots/gnss_recovery_timeline.png), and [cross-dataset drift](../plots/cross_dataset_drift.png) are generated from measured host replay outputs. They are not live Android screenshots or independent field ground truth.
