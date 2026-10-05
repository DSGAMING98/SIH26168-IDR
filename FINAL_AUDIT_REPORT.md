# NAVGHOST SIH26168 FINAL AUDIT REPORT

Audit date: 2026-10-05. Current APK: NavGhost 2.4.0 (code 41). All accuracy numbers below are labelled by source. This report does not assert a new physical-road accuracy result.

## 1. Executive Verdict

**NOT READY for full SIH26168 final-solution compliance; demonstrable as a research prototype.** The phone-only causal pipeline, EKF, gated on-device GRU and GNSS-denial/recovery logic are real. None of the four standard IO-VNBD S1 blackout windows meets the official under-10% drift target. Lane-level position, runtime road matching and an external-IMU/FOG edge path are not demonstrated.

## 2. Changes Made

- Published the full tracked Android project, current evidence summaries, selected plots and an evidence-first README rather than the prior partial source bundle.
- Made Google 3D credentials optional for building; the core and local ENU fallback remain keyless.
- Avoided restoring an opaque Google 3D vendor `Parcelable` that produced an observed Android 16 `BadParcelableException`. The map view is recreated and fed the next engine snapshot instead. This is a narrow lifecycle fix, not a comprehensive 3D certification.
- Fixed Phase 5 plotting for an output path outside the repository and exactly reproduced the 60-second replay.
- Built and installed the same-version signed candidate without clearing app data; deployed that candidate to the existing public download URL.

## 3. SIH26168 Requirement Matrix

The [full matrix](SIH26168_FINAL_REQUIREMENTS_AUDIT.md) has per-requirement status, code and result. Principal PASS items: phone-sensor architecture, causal synchronization, genuine runtime GNSS isolation, six-state EKF, frozen on-device GRU, offline estimator. Principal FAIL items: under-10% standard-window drift, lane-level accuracy, runtime map matching, generic external-IMU edge pathway. Field accuracy, cross-device generalization, uncertainty calibration and end-to-end latency remain PARTIAL.

## 4. Final Architecture

Android GPS and built-in IMU → causal 10 Hz synchronization → conditioning/alignment → six-state EKF and stationary constraints → optional OOD-gated GRU speed residual → engine-owned position/uncertainty → map presentation. During simulated denial runtime GNSS is null, while raw physical callbacks may be logged separately for evaluation. Recovery requires two distinct fresh fixes and a bounded correction. See the [technical overview](technical-evidence/docs/FINAL_TECHNICAL_OVERVIEW.md).

## 5. AI/ML Model

One-layer GRU, 32 hidden units, 10 input features, 20-step window, 4,257 parameters, 21,649-byte checkpoint; frozen SHA-256 `fa2169781f9e499dd87fdd00038a3b4a1326181b31938cec237a7802ae0bb4ec`. It predicts a bounded speed residual, not coordinates. Separated time blocks yielded 11,818 training and 3,489 validation windows. Source-domain speed MAE improved from 12.226 to 6.814 m/s. Zero-shot phone-domain results were mixed. See the [model card](technical-evidence/models/model_card.md).

## 6. Dead-Reckoning Results

| Frozen IO-VNBD S1 blackout | Reference travel | Raw final error | EKF final error | Hybrid final error | Hybrid drift |
|---|---:|---:|---:|---:|---:|
| 10 s steady | 154.16 m | 12.80 m | 32.97 m | 34.92 m | 22.655% |
| 30 s turning | 200.92 m | 135.30 m | 47.45 m | 37.31 m | 18.571% |
| 60 s stop/go | 262.79 m | 327.19 m | 95.08 m | 74.19 m | 28.232% |
| 120 s higher speed | 1706.39 m | 2354.89 m | 416.39 m | 656.62 m | 38.480% |

The [performance table](technical-evidence/results/FINAL_PERFORMANCE_TABLE.md) also contains RMSE, P95, maximum, uncertainty, recovery duration and the supplementary windows. These are host replays, not current moving-phone errors.

## 7. <10% Requirement Verdict

**FAIL: 0/4 standard windows pass.** Median drift is 25.44%; mean is 26.98%. A separately preselected 75-second surprise window reaches 3.855%, but does not justify a general under-10% claim. A defensible solution needs broader calibration/training and independently referenced, varied physical drives; changing a reporting threshold cannot solve this.

## 8. Map Matching

**Research-only; not in Android runtime.** The offline probabilistic road matcher improved 2/6 frozen windows relative to the best Phase 5 prior, and sometimes chose the wrong branch. Rendering a road tile or route is not localization map matching. See the [Phase 6 report](technical-evidence/docs/phase6_map_matching.md) and [before/after plot](technical-evidence/plots/map_matching_60s_before_after.png).

## 9. Cross-Dataset Generalization

Google Smartphone Decimeter 2022 supplied three evaluable moving windows: Pixel 4 XL Mountain View 30 s Hybrid 40.87% versus EKF 23.31%; Pixel 4 XL Mountain View 60 s 81.32% versus 80.78%; Pixel 5 Los Angeles 30 s 27.52% versus 64.15%. Hybrid helps once and hurts twice. The SDC steady 10 s window has zero reference distance, so drift is undefined. WHU, MoRPI, PPC and GREAT local payloads are not eligible for the same frozen comparison. See [Phase 8 methodology](technical-evidence/docs/phase8_cross_dataset_validation.md).

## 10. Real Android Phone Validation

Vivo V2513, Android 16, app 2.4.0: signed update installed over the existing app; indoor screen honestly showed `WAITING FOR GNSS` and local ENU fallback; two launches had no Android crash-buffer entry. Historical Phase 9.1 evidence measured approximately 50 Hz native IMU, 9.6 Hz normalized stream and 19.17 s first fix, with GNSS masking observed. Current outdoor first fix, moving blackout/IDR/recovery error, current average/P95 processing time, battery and thermal impact: **NOT AVAILABLE**. The observed Google 3D restore crash has a narrow code fix but no comprehensive field regression proof. Device instrumentation was intentionally not run on the data-bearing phone because its UI test persists a trip and changes a preference.

## 11. Automated Tests

Python **288/288**, Kotlin **187/187**; Android lint passed with **222 warnings, 0 errors**. Keyless/configured debug builds and configured signed release succeeded. The published Android checkout independently passed keyless `testDebugUnitTest`, `lintDebug` and `assembleDebug` with the installed SDK supplied via environment. The 60-second host replay reproduced its frozen metrics. Android instrumentation **0 run; not passed or failed**. The signed candidate hash is `3037f409caf79bfc76713636a2e81946b27de13902319a737f3da3450cca6f0e`.

## 12. Final Repository State

Engineering branch `codex/navghost-product-expansion`, focused code commit `74f57f3`. The judge-facing `main` checkout contains the current README, requirements matrix, full tracked Android source, reports, selected plots and data summaries. Existing unrelated dirty engineering files were deliberately excluded from the focused commit. See the Git history for the eventual publication commit; no history rewrite or force push is used. The live website points to the same-version signed APK.

## 13. Remaining Limitations

Under-10% drift and lane-level accuracy are unproven and fail available standard replay measurements. Runtime road matching, generic external IMU input and 200 Hz FOG validation are absent. Cross-phone ML transfer is inconsistent. Phone-level moving accuracy, sustained cadence/latency, battery, thermal, outdoor 3D stability and independent ground truth need further study. Uncertainty is covariance-derived, not a calibrated 95% region.

## 14. Judge-Facing Strengths

Real causal GNSS isolation; physics-first EKF with refusal-capable ML; one frozen model and Kotlin parity; explicit loss/reacquisition states; reproducible mixed-result benchmarks; full Android source, tests and a signed phone-installed release; transparent failure reporting rather than a cherry-picked success window.

## 15. Judge-Facing Risks

An evaluator can immediately challenge the official under-10% target, lane-level claim, lack of deployed map matching, external-IMU requirement, current field ground truth and zero-shot degradation. Demo videos and attractive maps are not accuracy proof. Avoid calling the APK certified for navigation or claiming the 3D lifecycle fix resolves every device/network issue.

## 16. FINAL BLIND RANKING DATA

Subjective audit scores out of 10, **not measured performance**: problem understanding 8; novelty 6; technical architecture 7; AI/ML 6; dead reckoning 5; map matching 2; GNSS recovery 6; accuracy 3; cross-device generalization 4; Android implementation 7; engineering depth 8; research integrity 9; GitHub quality 8; demo readiness 7; SIH requirement compliance 4; finals readiness 5.

## 17. Files I Should Send Back to ChatGPT

Send [README](README.md), [requirements matrix](SIH26168_FINAL_REQUIREMENTS_AUDIT.md), [judge summary](technical-evidence/results/FINAL_JUDGE_SUMMARY.md), [performance table](technical-evidence/results/FINAL_PERFORMANCE_TABLE.md), [architecture](technical-evidence/docs/FINAL_TECHNICAL_OVERVIEW.md), [map report](technical-evidence/docs/phase6_map_matching.md), [cross-dataset report](technical-evidence/docs/phase8_cross_dataset_validation.md), [field protocol/evidence](technical-evidence/docs/phase11_field_validation.md), [60 s trajectory](technical-evidence/plots/s1_60_stop_go_trajectory_comparison.png), [60 s error](technical-evidence/plots/s1_60_stop_go_position_error.png), [recovery timeline](technical-evidence/plots/gnss_recovery_timeline.png), [cross-dataset comparison](technical-evidence/plots/cross_dataset_drift.png), and both Git commit hashes. The signed APK is available from [the production download](https://navghost-idr.vercel.app/downloads/NavGhost-Android-v2.4.0.apk).
