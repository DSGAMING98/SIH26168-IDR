# NAVGHOST 120-SECOND FINAL ATTACK REPORT

## 1. Verdict

**120 s <10%: FAIL — 11.692%**

**Overall: 3/4 standard windows below 10%.**

The protected Android-installed candidate remains the strongest policy that passes all three protected short/mid-duration gates. A road-assisted research policy crossed 10% at 120 seconds, but was rejected because it severely regressed the 30-second turning standard. No failed road policy was deployed.

## 2. Final Drift Table

| Standard window | Protected final candidate | Gate |
|---|---:|---|
| 10 s | 8.503% | PASS |
| 30 s | 2.834% | PASS |
| 60 s | 3.765% | PASS |
| 120 s | 11.692% | FAIL |

Policy SHA-256: `57b535ca37e925aa75342b4fe289284ff0152fcd5f49a3dba212100eae0fb590`.

## 3. 120-Second Error Budget

The protected 120-second replay ends at 199.510 m absolute position error. Offline-only decomposition shows a 252.572 m cumulative speed-distance deficit, approximately 249.210 m along-track error, 46.530 m lateral error, and 7.939 degrees mean absolute heading error. The dominant source is therefore absolute-speed observability and accumulated along-track deficit, not lateral map error.

| Segment | Mean speed bias | Distance deficit/excess | Mean absolute heading error | End along-track error | End lateral error |
|---|---:|---:|---:|---:|---:|
| 0–20 s | -4.915 m/s | -98.790 m | 5.722° | -96.999 m | 6.146 m |
| 20–40 s | -1.231 m/s | -24.624 m | 7.617° | -82.570 m | -60.805 m |
| 40–60 s | -0.992 m/s | -19.835 m | 6.830° | -120.530 m | -69.182 m |
| 60–80 s | -1.165 m/s | -23.181 m | 4.694° | -147.756 m | -27.096 m |
| 80–100 s | -0.764 m/s | -15.271 m | 8.823° | -183.201 m | 32.410 m |
| 100–120 s | -3.543 m/s | -70.871 m | 13.942° | -249.210 m | 46.530 m |

Reference columns were attached only after runtime prediction completed; they never entered the estimator.

## 4. Attempts

| Attempt | Hypothesis/change | 120 result | Protected-window status | DEV / cross-device result | Decision |
|---|---|---:|---|---|---|
| 1 | Evolve the long-outage speed floor with causal stride acceleration | Not run on standards; validation selected scale 0.00 | Protected | Every nonzero scale worsened both locked validation windows | REJECTED |
| 2 | Pre-loss acceleration bias / bounded affine calibration | 11.410% | 60 s regressed to 13.165% | Validation preferred bias-only; affine fit was inconsistent | REJECTED |
| 3 | Tiny training-only bounded long-horizon correction head | 11.692% | 10/30/60 unchanged | Validation gain was negligible; correction stayed below active floor | REJECTED |
| 4 | Validation-selected soft road-heading gain 0.5 | 9.952% | 30 s regressed to 19.782% | Validation improved; cross-device road cache not applicable | REJECTED |
| 5 | Active-turn veto at validation-selected 0.12 rad/s | 9.915% | 30 s regressed to 16.803% | Veto applied, but binary authority remained unsafe | REJECTED |
| 6 | Same frozen gain/threshold with smooth turn-rate authority taper | 10.080% | 30 s regressed to 16.590% | DEV mean 10.881% → 10.042%; still unsafe on standard turn | REJECTED |

No candidate was selected using scenario identity, future sensors, outage end time, post-loss GNSS, or benchmark reference truth.

## 5. Final Runtime Policy

The final policy remains the protected causal 3/4 estimator: six-state EKF, direct-speed IMU GRU, early low-information suppression, OOD gate, stationary veto, validation-frozen 45-second long-outage transition, and a pre-loss reconstructed speed floor. Road-heading assistance is research-only and not deployed.

## 6. Python/Kotlin Parity

The deployed focused direct-speed GRU has three Python/Kotlin golden windows within `1e-4` m/s speed and `1e-5` OOD exceedance. Model checkpoint SHA-256: `e548cac929ae78c0a6449f8bb6d0cecd772166ae0fcaf140bb1a096d4055a2c1`. The original frozen released GRU remains unchanged at `fa2169781f9e499dd87fdd00038a3b4a1326181b31938cec237a7802ae0bb4ec`.

## 7. Android Verification

The protected candidate is installed in place on vivo V2513 / Android 16 as NavGhost 2.4.0 (`versionCode 41`). App data and signing identity were preserved. Accelerometer, gyroscope, magnetometer, gravity and rotation-vector registrations succeeded; the navigation foreground service started; no fatal exception or ANR was observed during the stationary USB check. This does not prove moving tunnel accuracy.

## 8. Tests

- Python: 300 passed.
- Kotlin/JVM: 200 passed.
- Python/Kotlin focused-model parity: PASS.
- Android lint and release lint-vital: PASS.
- Debug and signed release assembly: PASS.

## 9. Moving Validation

**USER PHYSICAL ACTION REQUIRED:** safely mount the phone, obtain fresh outdoor GNSS, perform a real 60–120 second outage/tunnel and reacquisition, export the session, and record an independent reference if available. Stationary USB validation is not moving localization evidence.

## 10. GitHub

Focused estimator source commit: `e5d284de3f9f78b2ca55acf29f7b6d15ad64ea75`.

The public evidence is updated with this report, the protected policy/results, segment error budget, attempt manifests, Android verification facts, hashes and limitations. Older conflicting accuracy summaries are marked historical/superseded rather than deleted.

## 11. Vercel

The production website reports the same four-window table and explicit **3/4 under 10%** status. It labels the APK as a focused research candidate and keeps moving validation, lane-level validation and runtime map matching limitations visible.

## 12. Final APK

- Version: NavGhost 2.4.0 (`versionCode 41`), focused research candidate.
- SHA-256: `cc1066ae3ba073fe657564624b2152ba67a3812eb5dcc4b4ac50bfa5808ff1fd`.
- Signing certificate SHA-256: `638d559143fa28181e3b498157706b3a087cbe18144560e3650281c66c99f281`.
- Signing continuity: PASS; installed in place without clearing app data.

## 13. SIH Accuracy Status

**3/4 STANDARD WINDOWS BELOW 10%; 120-SECOND LIMIT REMAINS.**

This is not full SIH accuracy compliance. Lane-level accuracy is unavailable. Runtime road matching remains undeployed because the validation-selected road policy failed the protected turning gate. Cross-device generalization remains mixed: Pixel 4 XL MTV30 41.281%, Pixel 4 XL MTV60 18.212%, Pixel 5 LAX30 6.473%.

## 14. Grand Finale Readiness

NavGhost is a strong, reproducible research prototype with an Android-validated on-device estimator, honest safety gates, offline operation, GNSS recovery architecture and substantially improved source-domain results. It is ready for a transparent demonstration, but not for a claim of universal under-10% drift, lane-level positioning, or completed moving tunnel validation. The remaining engineering priority is new synchronized two-minute moving data with independent truth, not further tuning against these four standards.
