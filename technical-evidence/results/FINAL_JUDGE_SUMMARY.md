# NavGhost: final judge summary

**Status: research prototype ready to demonstrate, but not ready to claim full SIH26168 final-solution compliance.** NavGhost is a phone-only intelligent dead-reckoning system for the period between the last trusted satellite fix and verified GNSS recovery. It addresses position continuity when GNSS disappears, rather than merely displaying a cached map. The project does **not** yet demonstrate the SIH target of under-10% drift across standard blackouts, lane-level position, runtime road matching or the requested external-IMU/FOG edge pathway.

## What happens at runtime

Android's GPS provider and built-in accelerometer, gyroscope, gravity/rotation sensors and optional magnetometer feed a causal 10 Hz normalized stream. Motion conditioning and phone-to-vehicle alignment feed a six-state EKF. A frozen 4,257-parameter GRU predicts only a bounded **speed residual**, not latitude or longitude. Its correction is reduced or rejected when input features are out of distribution. The engine carries covariance-derived uncertainty and applies stationary constraints.

When a simulated tunnel begins, the estimator's runtime GNSS fields are null. Physical GPS callbacks can continue into a separate evaluator-only log, but cannot feed the estimator. If alignment was never established, the engine holds position rather than inventing direction. On return, it requires two distinct fresh fixes and applies a bounded correction. A new loss during recovery returns to dead reckoning. The map is a view of the engine output. Google 3D, MapLibre and local ENU do not supply hidden location or road constraints to the estimator.

## What the AI and evidence show

The model was trained on separated time blocks of one IO-VNBD S1 journey: 11,818 training and 3,489 validation windows. Source-domain validation speed MAE fell from 12.226 to 6.814 m/s, but zero-shot results on two Google Smartphone Decimeter phone models were mixed. Android uses a dependency-free Kotlin implementation of the frozen GRU with Python/Kotlin parity tests. The model hash is `fa2169781f9e499dd87fdd00038a3b4a1326181b31938cec237a7802ae0bb4ec`.

| Frozen IO-VNBD S1 blackout | Reference travel | Hybrid final error | Drift |
|---|---:|---:|---:|
| 10 s steady | 154.16 m | 34.92 m | 22.655% |
| 30 s turning | 200.92 m | 37.31 m | 18.571% |
| 60 s stop/go | 262.79 m | 74.19 m | 28.232% |
| 120 s higher speed | 1706.39 m | 656.62 m | 38.480% |

**Under-10% target: DOES NOT MEET.** The standard-window median is 25.44%. A separately preselected 75-second surprise window achieved 3.855%, but one good window is not evidence of general compliance. The 10-second raw inertial baseline beat Hybrid; the 120-second EKF beat Hybrid. These failures are retained in the [complete performance table](FINAL_PERFORMANCE_TABLE.md).

## Map matching and generalization

A probabilistic road matcher was evaluated offline on the S1 map. It improved only two of six frozen windows relative to the best available Phase 5 prior and sometimes selected the wrong branch. It is **research-only**, not in the Android runtime. Rendering roads on a map is not map matching. Google Smartphone Decimeter 2022 supplied three evaluable moving windows on Pixel 4 XL and Pixel 5; Hybrid improved EKF once and degraded it twice. WHU, MoRPI, PPC and GREAT are not claimed as validated datasets with the local payloads available.

## Real phone and release state

The current app is NavGhost **2.4.0**. On 2026-10-05 it launched on a USB-connected Vivo V2513 running Android 16 and showed the honest indoor `WAITING FOR GNSS` state. An observed Google 3D restore crash from an opaque saved Play Services `Parcelable` was addressed by not handing saved vendor state back to the 3D view. The signed update installed over the existing app without clearing data, launched and relaunched twice with no crash in the Android crash buffer. This is a narrow lifecycle check, not proof that every Google 3D device/network path is fixed. Earlier physical evidence measured roughly 50 Hz native IMU, 9.6 Hz normalized stream, a 19.17-second first fix and runtime masking of a fresh physical fix. Those are historical acquisition/isolation observations, not this audit's new road-accuracy result. No new outdoor first fix, moving blackout/recovery accuracy, battery or thermal figure was measured today. The build now succeeds without a Google 3D key and retains the local ENU fallback; configured Google 3D also builds.

Verification on this audit: **288/288 Python tests, 187/187 Kotlin tests, successful Android lint (222 warnings, 0 errors), keyless and configured debug builds, and a signed release build**, plus an exact independent reproduction of the 60-second replay metrics. Android instrumentation was not run on the user's existing data-bearing phone because a UI test writes a trip and changes a setting.

For judging, demonstrate the live phone status and clearly labelled synthetic/public replay. Present the causal GNSS isolation, Kotlin GRU parity, uncertainty and honest failure table as strengths. Do not describe the current APK as independently proven to stay within 10% drift, maintain lane-level accuracy or perform on-device road matching. A safe mounted-vehicle study with an independent position reference, varied devices, a validated road matcher and an external-IMU interface remain decisive work.
