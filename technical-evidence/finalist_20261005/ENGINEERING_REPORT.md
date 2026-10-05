# NavGhost engineering evidence — 2026-10-05

**MORE ENGINEERING REQUIRED. App, signed build and website remain version 2.4.0.**

The four baseline windows reproduced before changes. Historical outputs, configurations, scaler and checkpoint remain intact. Seven causal candidate variants were evaluated on the same windows and existing development intervals. These are exploratory engineering comparisons, not newly blind holdouts. No reference was supplied to a runtime estimator.

## Full standard comparison

| Window (s) | Baseline hybrid % | Candidate classical % | Candidate hybrid % | Candidate final error m | Candidate mean error m | Candidate RMSE m | Candidate P95 m | Candidate maximum m |
|---|---|---|---|---|---|---|---|---|
| 10 | 22.655 | 8.503 | 13.739 | 21.180 | 8.966 | 11.031 | 19.692 | 21.180 |
| 30 | 18.571 | 12.216 | 8.519 | 17.118 | 24.332 | 27.556 | 44.021 | 44.817 |
| 60 | 28.232 | 35.467 | 27.257 | 71.629 | 46.362 | 51.425 | 71.479 | 71.629 |
| 120 | 38.480 | 20.923 | 32.932 | 561.942 | 197.859 | 259.531 | 523.333 | 561.942 |

Baseline: 0/4 below 10%; mean 26.985%, median 25.444%, worst 38.480%. Candidate: 1/4; mean 20.612%, median 20.498%, worst 32.932%. Candidate is NOT deployed to Android.

## Root causes and decisions

- Baseline 10 s moving yaw MAE is 11.883 degrees; diagnostic integrated heading-error component is 32.277 m. At 30 s, initial heading error is -24.677 degrees and GNSS speed initialization is stale. At 60 s, speed and residual acceleration bias dominate; stationary updates were not false-positive against reference speed above 2 m/s. At 120 s, hybrid signed speed bias is -4.004 m/s and initial yaw error is -26.697 degrees. Diagnostic components are interacting vectors, not additive causal percentages.
- Last distinct pre-loss fixes are 4–8 s old. Measured sample intervals remain 0.093–0.107 s; no large timestamp gap explains these failures.
- Latest moving phone course plus pre-loss gyro propagation/bias improves all four source-domain hybrid windows. It still worsens one development case (10.167% to 14.633%) and the MTV30 transfer case. Retain as research, not an Android accuracy claim.
- Speed extrapolation and moving accelerometer-bias estimates regress other windows; disabled. Turning-velocity pseudo-measurements regress development and long-window results; disabled.
- Training uses independent classical speed, while original hybrid inference feeds corrected speed back. A separate classical prior removes that mismatch but makes DEV2020 much worse (10.167% to 159.758%). It is disabled; replacing the model or deploying this change without retraining/validation would be unjustified.
- Hard OOD from the start reproduces classical output in a new test. This does not prove recovery to a never-corrected classical trajectory after previously accepted ML updates, nor guarantee that an in-distribution prediction improves truth.

## Runtime and device status

Android core navigation remains the existing EKF/GRU/recovery pipeline. A new generic SI-unit input adapter and Android forwarding adapter are tested. Synthetic host replay: 20,000 inputs at a 200 Hz equivalent cadence, 1,000 normalized engine updates at 10 Hz. One host run averaged 0.01171246 ms/input, P95 0.0239 ms/input, 85,379 inputs/s. This is not physical FOG, native 200 Hz estimator accuracy, phone timing, battery, or memory evidence. Missing attitude remains missing; no synthetic attitude is invented.

293 Python tests and 194 Kotlin tests pass; debug build and Android lint pass. A first lint run crashed internally during a concurrent source edit; a stable rerun passed. No test was removed. A source-boundary test was updated to verify the new forwarding path and retained publication ordering.

The final signed 2.4.0 APK was installed in place on a vivo V2513 running Android 16 without clearing app data. Package identity, signature continuity, permissions and inertial-sensor availability were verified. Splash/main and all six primary screens passed stationary smoke checks; three cold launches took 253–312 ms; the final observed total PSS was 90,229 KB; Android's crash buffer remained empty. The tunnel control correctly rejected a test before live navigation prerequisites. Indoor stationary checks did not establish a trusted outdoor fix, moving blackout/recovery accuracy, road/lane accuracy or estimator latency. See [Android device verification](ANDROID_DEVICE_VERIFICATION.md).

## Maps and field work

Road matching remains RESEARCH ONLY: existing frozen evidence shows branch-selection regressions, and no new safe runtime benefit was established. No lane-level truth exists. The existing automatic 10/30/60/120 s field presets remain available; no drive was fabricated.

**MOVING VEHICLE VALIDATION REQUIRED**

While parked: securely mount the phone, grant precise location, start live sensing outdoors, and arm the automatic preset. Drive normally without driver interaction; the app waits for fresh GNSS and alignment. A passenger may operate controls. After parking, stop and export the session ZIP to a private directory. Run tools/validate_phase11_android_session.py on that directory. Same-phone GNSS is a proxy, not survey-grade truth.

## Reproduction

Use the existing environment: tools/finalist_error_budget.py; tools/finalist_initialization_ablation.py --suite initialization (or feedback_bias / turn_constraint); tools/run_phase8_validation.py --output results/finalist_20261005/cross_device_baseline; tools/finalist_cross_device_candidate.py; tools/finalist_report.py. Source datasets must be acquired separately. Do not put private phone traces in Git.

All failed candidates remain in all_ablations.csv; aggregates include median and worst-case. speed_metrics.csv contains MAE/RMSE/P95/bias/correlation and speed bins. Cross-device baseline/candidate directories retain all four windows, including the zero-distance case with undefined drift.
