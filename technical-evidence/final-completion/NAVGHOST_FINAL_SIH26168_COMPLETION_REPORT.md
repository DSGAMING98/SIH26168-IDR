# NAVGHOST FINAL SIH26168 COMPLETION REPORT

## 1. Verdict

**4/4 NOT ACHIEVED**

Grand Finale readiness: **72%**. The Android product, recovery state machine, offline execution, evidence pipeline, external-sensor software boundary, signed release, website, and reproducibility gates are usable. The central positioning claim remains below the requested evidence threshold: the deployed estimator passes 0/4 standard windows below 10% drift, and the strongest quarantined research family passes 2/4 but fails its release gate.

## 2. Requirement Completion

| Requirement | Previous | Final | Evidence |
|---|---:|---:|---|
| One causal estimator on all frozen windows | PASS | PASS | Same half-open benchmark windows and metrics; no runtime reference access |
| 4/4 standard windows below 10% | 0/4 | 2/4 research; 0/4 deployed | `ablation/ablation.csv` |
| Robust velocity estimation | FAIL | PARTIAL | Direct-speed GRUs improve validation and 30/60 s, but fail 10/120 s and development consistency |
| Adaptive classical/ML safety | PASS | PASS, unchanged | Frozen OOD and innovation gates; opening OOD did not solve failures |
| Cross-device robustness | PARTIAL | PARTIAL | Existing Pixel 4 XL / Pixel 5 evidence remains mixed; candidate not promoted |
| GNSS recovery logic | PASS | PASS in automated tests | 25 focused speed/timing/recovery tests passed; moving reacquisition still pending |
| Runtime map constraints | RESEARCH | RESEARCH ONLY | Existing matcher improves 2/6 and regresses 4/6 cases |
| Road-level evidence | PARTIAL | PARTIAL | Map display/route features exist; no safe estimator-wide gain established |
| Lane-level evidence | NOT AVAILABLE | NOT AVAILABLE | No lane-level truth; no accuracy claim made |
| External IMU pathway | PARTIAL | SOFTWARE PATH COMPLETE | 20,000-input host replay and Android forwarding adapter; no physical FOG |
| Android release | PASS | PASS, unchanged | vivo V2513 Android 16, 2.4.0(41), in-place install |
| Public APK/site | PASS | PASS, unchanged | Production site and APK endpoint return HTTP 200 |

## 3. Drift

All values are final relative position error divided by measured reference distance. The research result uses one causal direct-speed/IMU GRU, one configuration, and the same frozen windows.

| Window | Baseline deployed | Previous course candidate | Final research candidate |
|---:|---:|---:|---:|
| 10 s | 22.655% | 13.739% | 26.095% |
| 30 s | 18.571% | 8.519% | 3.740% |
| 60 s | 28.232% | 27.257% | 6.606% |
| 120 s | 38.480% | 32.932% | 30.905% |

The alternate direct-speed model that retained the classical-speed feature produced 20.112%, 6.028%, 8.703%, and 30.967%. It also failed the release gate.

## 4. Final <10% Result

**2/4 in research; 0/4 in the deployed 2.4.0 release.**

No benchmark-specific parameters, future samples, hidden VBOX/reference fields, altered windows, altered metric, or scenario identifiers were supplied to a runtime estimator. The direct models were trained only on the existing disjoint training blocks and selected only on the existing validation blocks.

## 5. Final Estimator

The deployed estimator remains the verified 2.4.0 pipeline:

1. strictly pre-outage phone GNSS initialization;
2. gravity-aligned and causally filtered phone IMU preprocessing;
3. six-state EKF: East, North, forward speed, yaw, acceleration bias, gyro bias;
4. nonnegative speed and physical covariance propagation;
5. stationary zero-speed update when the causal motion detector permits it;
6. frozen 32-unit, one-layer GRU residual measurement;
7. OOD and normalized-innovation gating before ML influence;
8. bounded GNSS recovery through the existing state machine.

No research estimator was deployed because none met both the four-window target and regression/cross-device gates.

## 6. Heading Solution

The strongest causal heading initialization anchors to the last trustworthy moving phone course and propagates to outage start using only measured gyro and a robust pre-loss course-derived gyro bias. It improves the four standard-window mean drift from 26.985% to 20.612%, but regresses DEV2020 from 10.167% to 14.633% and regresses the Pixel 4 XL MTV30 transfer case. It remains research-only.

## 7. Velocity / Bias Solution

The root cause is observability, not a timestamp gap. Phone fixes are typically 4–8 seconds old at outage start. In the 60/120-second windows, recent position-derived speeds are about 6.8–7.0 m/s while reference speed at outage start is about 14.2/12.0 m/s. Accelerometer projection sometimes has the wrong net sign for the real speed change; moving-bias estimation and simple extrapolation regress other windows.

Two quarantined 14,657-parameter GRUs were evaluated:

- direct speed with classical-speed input: validation MAE 2.035 m/s; 2/4 standard windows;
- direct speed from IMU/motion features with the classical-speed feature removed: validation MAE 1.727 m/s; 2/4 standard windows.

The latter still produced 30.905% at 120 seconds, 26.095% at 10 seconds, and stayed above 10% on two of three development intervals. This is a defensible physical/data limit for this phone-only, single-journey evidence set.

## 8. ML Arbitration

The released frozen GRU and its OOD/innovation arbitration remain unchanged. Disabling the OOD limit changed the difficult standard cases by less than 0.3 percentage points, so the gate is not the root cause. The direct-speed models were not promoted because validation improvement did not generalize consistently to the frozen standards or development cases.

Released GRU SHA-256: `fa2169781f9e499dd87fdd00038a3b4a1326181b31938cec237a7802ae0bb4ec`.

## 9. Map Matching

**RESEARCH ONLY**

The frozen matcher improves 2/6 evaluated cases and regresses 4/6. It is not used to claim the 4/4 result and was not deployed as an accuracy fix.

## 10. Cross-Device

Existing baseline-to-course-candidate drift evidence remains:

- Pixel 4 XL MTV10 stationary: about 0.060 m final error for both; drift undefined because reference distance is zero;
- Pixel 4 XL MTV30: 40.866% to 41.160% (regression);
- Pixel 4 XL MTV60: 81.323% to 80.210%;
- Pixel 5 LAX30: 27.522% to 26.183%.

This is insufficient for a cross-device accuracy claim. The candidate was therefore not ported to Android.

## 11. GNSS Recovery

The existing ACTIVE → DEGRADED/LOST → VERIFYING/RECOVERING → ACTIVE state machine, stale-fix rejection, multiple-fix confirmation, and bounded handoff remain intact. Twenty-five focused metro, speed, timing, and recovery tests pass. A stationary connected phone cannot supply a real moving loss/reacquisition measurement.

## 12. Road/Lane Evidence

Road-level rendering, directions, and static-road research infrastructure exist. No safe runtime road constraint improved the full evaluation set. Lane-level accuracy is **NOT AVAILABLE** because no lane-level reference is present; the app must not claim lane-level positioning.

## 13. External IMU / FOG

**EXTERNAL IMU SOFTWARE PATH COMPLETE. PHYSICAL FOG VALIDATION PENDING.**

The generic SI-unit input adapter and Android forwarding adapter are covered by tests. Host replay processed 20,000 inputs at a 200 Hz equivalent cadence and emitted 1,000 normalized 10 Hz engine updates. The measured host run averaged 0.0117 ms/input with P95 0.0239 ms/input. This is software-path evidence, not physical FOG accuracy or phone power evidence.

## 14. Android Validation

- Device: vivo V2513, Android 16, serial `10BFAB14ED0026H`.
- Installed package: `org.sih26168.idrlogger` 2.4.0, versionCode 41.
- In-place installation preserved first install time `2026-09-27 15:52:53`; no app data was cleared.
- Installed APK matched the final release SHA-256.
- Cold launch: 666 ms.
- Sampled frames: 414; janky frames: 47 (11.35%).
- Frame P50/P90/P95/P99: 13/22/34/200 ms.
- Total PSS: 301,946 KB; RSS: 404,644 KB.
- Crash scan: empty.
- Current indoor/stationary state: waiting for GNSS; accelerometer, gyro, gravity, and rotation-vector sensors available.

## 15. Moving Validation

**USER PHYSICAL ACTION REQUIRED**

Securely mount the phone in a vehicle, grant precise location, acquire a fresh outdoor GNSS fix, drive a safe route with a passenger operating the app, include a real 60–120 second tunnel/covered outage and full reacquisition, then park and export the private session ZIP. Do not clear app data. A survey-grade reference is required for a defensible absolute drift claim; same-phone GNSS is only a recovery proxy.

## 16. Tests

- Python: **293 passed**, 0 failed, 2 dependency deprecation warnings.
- Kotlin/JVM: **194 passed**, 0 failed, 0 skipped.
- Focused metro/speed/timing/recovery: **25 passed**.
- Android lint: **0 errors, 0 fatal, 229 warnings**.
- Debug build: PASS.
- Signed release build: PASS.
- Research ablation reproduction: PASS; 7 cases × 4 candidates written to `ablation/ablation.csv`.

## 17. Remaining Failures

1. The requested 4/4 below 10% target is not achieved.
2. The deployed release remains 0/4; research reaches 2/4 only.
3. Sustained 120-second speed is not observable reliably enough from this phone IMU/model/data combination.
4. The best heading initialization has development and cross-device regressions.
5. Map matching is not globally safe.
6. Moving GNSS loss/recovery, sustained phone performance, battery, and physical FOG evidence require physical action/hardware.
7. Lane-level truth is unavailable.

## 18. Deployment

- GitHub: `https://github.com/DSGAMING98/SIH26168-IDR`
- Current public release commit before this evidence-only update: `1e31bd28e1c9f6a914fc9a98472bc6b8d17de5ee`
- APK: `https://navghost-idr.vercel.app/downloads/NavGhost-Android-v2.4.0.apk`
- Version: 2.4.0 (41)
- APK SHA-256: `c0f0ff3e4551e242f90d9b900ec6e7cc77d66d16108c71c60290fd5e9d4deaed`
- Signing certificate SHA-256: `638d559143fa28181e3b498157706b3a087cbe18144560e3650281c66c99f281`
- Website: `https://navghost-idr.vercel.app/` (HTTP 200 verified 2026-10-06)
- APK endpoint: HTTP 200, 56,186,778 bytes verified 2026-10-06.

No APK or website was redeployed because no estimator survived the release gate. Publishing a version bump with worse standard/development behavior would misrepresent progress.

## 19. Final Readiness Scores

- Technical: **78%**
- Accuracy: **45%**
- Android: **88%**
- Evidence: **86%**
- SIH compliance: **74%**
- Grand Finale readiness: **72%**

## 20. Independent Review Links

- Repository: `https://github.com/DSGAMING98/SIH26168-IDR`
- README: `https://github.com/DSGAMING98/SIH26168-IDR/blob/main/README.md`
- Judge evidence: `https://github.com/DSGAMING98/SIH26168-IDR/blob/main/SIH26168_JUDGE_EVIDENCE.md`
- Requirements audit: `https://github.com/DSGAMING98/SIH26168-IDR/blob/main/SIH26168_FINAL_REQUIREMENTS_AUDIT.md`
- Release report: `https://github.com/DSGAMING98/SIH26168-IDR/blob/main/RELEASE_2_4_0.md`
- Final completion report: `https://github.com/DSGAMING98/SIH26168-IDR/blob/main/technical-evidence/final-completion/NAVGHOST_FINAL_SIH26168_COMPLETION_REPORT.md`
- Reproducible ablation CSV: `https://github.com/DSGAMING98/SIH26168-IDR/blob/main/technical-evidence/final-completion/ablation.csv`
- Ablation manifest/model hashes: `https://github.com/DSGAMING98/SIH26168-IDR/blob/main/technical-evidence/final-completion/manifest.json`

The release was held deliberately: the evidence supports a stable prototype and serious engineering progress, but not a scientifically honest claim of 4/4 sub-10% phone-only dead reckoning.
