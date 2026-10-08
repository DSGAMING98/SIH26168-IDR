# SIH26168 judge evidence

> **Current status (2026-10-08):** the protected causal candidate achieves 8.503%, 2.834%, 3.765%, and 11.692% drift at 10/30/60/120 seconds: **3/4 below 10%**. It passes 300 Python and 200 Kotlin tests plus parity, lint and signed build checks. The 120-second target, lane-level accuracy and moving tunnel validation remain incomplete. See the [current focused report](technical-evidence/accuracy-attack-20261007/NAVGHOST_120_SECOND_FINAL_ATTACK_REPORT.md). The older tables below are historical/superseded.

2026-10-06: working research prototype; **MORE ENGINEERING REQUIRED**.
App, signed build and website remain version 2.4.0 (41). Device checks are recorded separately from moving accuracy.

| SIH Requirement | NavGhost Implementation | Result | Evidence |
|---|---|---|---|
| GNSS denial | Runtime masking; reference log separate | PASS, host tests; physical evidence historical | [Architecture](technical-evidence/docs/FINAL_TECHNICAL_OVERVIEW.md) |
| Dead reckoning | Six-state EKF, causal conditioning/alignment | PASS implementation; accuracy limited | [Reproduced results](technical-evidence/finalist_20261005/comparison.csv) |
| AI/ML | Frozen GRU speed residual, 4,257 parameters | PASS implementation; benefit mixed | [Model card](technical-evidence/models/model_card.md) |
| Velocity estimation | Classical propagation + optional learned correction | PARTIAL | [Speed errors and bins](technical-evidence/finalist_20261005/speed_metrics.csv) |
| Map matching | Offline probabilistic matcher only | FAIL runtime requirement | [Historical map study](technical-evidence/docs/phase6_map_matching.md) |
| GNSS recovery | Distinct fresh-fix verification and bounded correction | PARTIAL: host-tested; moving phone recovery unmeasured | [Recovery](technical-evidence/docs/phase7_reacquisition.md) |
| Under-10% drift | Four unchanged IO-VNBD windows | FAIL: public baseline 0/4; research candidate 1/4 | [Full comparison](technical-evidence/finalist_20261005/comparison.csv) |
| Android deployment | Signed 2.4.0 build | PASS stationary deployment; moving validation pending | [Device verification](technical-evidence/finalist_20261005/ANDROID_DEVICE_VERIFICATION.md) |
| Offline operation | Core estimator needs no network; local ENU fallback | PASS architecture and local-fallback UI; outdoor route unmeasured | [Android source](technical-evidence/android/android/) |
| Cross-device validation | Pixel 4 XL / Pixel 5 locked zero-shot windows | PARTIAL: mixed; no target-label training | [Baseline](technical-evidence/finalist_20261005/cross_device_baseline.csv), [candidate](technical-evidence/finalist_20261005/cross_device_candidate.csv) |
| External IMU interface | SI-unit input contract, separate GNSS, Android/replay adapters | PASS software contract only; physical FOG pending | [Adapter](technical-evidence/android/android/app/src/main/java/org/sih26168/idrlogger/engine/ExternalSensorAdapter.kt) |
| Lane-level accuracy | No lane-level reference study | FAIL evidence requirement | [Engineering report](technical-evidence/finalist_20261005/ENGINEERING_REPORT.md) |

## WHAT RUNS ON THE PHONE TODAY

The final signed 2.4.0 APK was installed as an in-place upgrade on a vivo V2513 running
Android 16 without clearing app data. Splash/main launch and the 3D, routing, dashboard,
nearby, trips and insights screens passed stationary smoke checks. Local ENU and map
presentation were present; required permissions were granted; accelerometer, gyroscope,
magnetometer, linear acceleration and rotation-vector sensors were exposed. Three cold
launches completed in 253–312 ms and Android's crash buffer remained empty. Tunnel-test
activation was correctly rejected before live prerequisites. This is stationary deployment
evidence, not moving localization accuracy. See the [device report](technical-evidence/finalist_20261005/ANDROID_DEVICE_VERIFICATION.md).

The 2026-10-06 repeat gate installed the same signed APK in place, retained the original
install time, and read back an installed APK hash identical to the release. Focused metro
stop/resume, speed-bound, timing and recovery replay passed 25/25 tests before the full
194-test Android suite. The September 25 field observation predates those safeguards;
a new moving metro/vehicle run is still required to validate their physical behavior.

## WHAT REMAINS RESEARCH / PENDING

The heading/gyro-bias candidate is offline research, not Android navigation code.
Its standard drift is 13.739%, 8.519%, 27.257%, 32.932%. All tested candidates,
including regressions, are retained in [ablations](technical-evidence/finalist_20261005/all_ablations.csv).
Road constraints, lane-level truth, dependable cross-device ML benefit, calibrated
uncertainty, physical FOG, outdoor GNSS/recovery measurement, and safe moving validation remain open.

Host verification: **293 Python tests, 194 Kotlin tests, lint, debug and signed release builds passed**.
Synthetic adapter replay: 20,000 inputs / 1,000 engine outputs; 200 Hz equivalent input,
10 Hz engine cadence; 0.0117 ms mean and 0.0239 ms P95 per input in one host run.
This is not physical sensor fidelity or phone latency.

**MOVING VEHICLE VALIDATION REQUIRED.** Use the [safe field protocol](technical-evidence/docs/phase11_field_validation.md).
