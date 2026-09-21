# NavGhost final judge summary

## Problem

Offline maps can display cached road data while GNSS is available. SIH26168 addresses the different failure where GNSS itself becomes unavailable or unreliable. The product statement is: **We are not predicting where the vehicle should be. We are estimating where the vehicle is.**

## Architecture

A standalone Android foreground service causally synchronizes native phone sensors near 10 Hz, performs vehicle alignment, conditions motion, propagates a six-state EKF, optionally applies an OOD-gated 4,257-parameter frozen GRU speed residual, and reconciles boundedly when fresh GNSS returns. No route, destination, OBD-II, custom hardware, cloud, account, required map key or laptop is required.

## Live Android implementation

**NavGhost — Navigation Beyond GNSS** version 1.1.0 has LIVE, DEMO and SYSTEM. LIVE is map-dominant and shows the engine marker, heading, state-colored trajectory, speed, uncertainty halo, localization/alignment/AI state and safe field controls. DEMO is always `NOT LIVE`, with a deterministic 27-second judge story, visible phase timeline and public IO-VNBD evaluator replay. SYSTEM exposes sensors, GNSS, localization, AI/OOD, field test, session, performance and map health. The About sheet accurately attributes the SIH26168 problem statement to ISRO / Department of Space without implying endorsement or certification.

## GNSS isolation and AI safety

During simulated tunnel loss all runtime GNSS fields are null even if physical callbacks continue in an evaluator-only log. The engine rejects malformed hidden fixes independently. The map provider has no location API; only `IdrEngine` can drive the marker. Hard OOD becomes `AI SAFETY FALLBACK`, not an unsafe correction. Loss before alignment holds position as `CALIBRATION REQUIRED`.

## Performance and benchmark evidence

Host engine-only timing is 11,545 samples/s, 0.0866 ms average and 0.185 ms P95 versus a 10 Hz input. Frozen model SHA-256 is `fa2169781f9e499dd87fdd00038a3b4a1326181b31938cec237a7802ae0bb4ec`.

The named public replay `S1_60_STOP_GO` is 60 seconds / 262.794 m. Raw DR final error is 327.185 m; Phase 5 Hybrid is 74.192 m / 28.232% drift. This is not cherry-picked as a universal claim: standard Hybrid drift was 22.655%, 18.571%, 28.232% and 38.480% for 10/30/60/120 seconds, and cross-device generalization was moderate.

Release validation is 56/56 Kotlin/JVM tests and 228/228 Python tests with a successful offline APK build. The frozen estimator/model configuration is unchanged.

## Physical-phone evidence

Existing open-sky evidence verified approximately 50 Hz IMU, approximately 9.6 Hz runtime, visible/used satellites, a 19.17-second first fix, physical GPS callbacks and a real fix masked from runtime. The user also reported the Phase 11 app working correctly. No private GPS trace is committed and no new Phase 12 road-accuracy or endurance result is fabricated.

## Field validation, privacy and offline behavior

Automatic 10/30/60/120-second field tests run warm-up, readiness, baseline, blackout and recovery without driver interaction. Export is explicit and local. The validator keeps private sessions outside Git and treats same-phone GNSS only as an evaluation proxy. The official Google Maps SDK is an optional visual canvas configured only from ignored local properties. Google My Location is disabled; all displayed positions come from `IdrEngine`. Missing key/network/services falls back to local ENU, and map failure cannot pause IDR.

## Known limitations

No universal `<10%` drift, survey-grade accuracy, calibrated 95% uncertainty, worldwide road map, battery endurance or official deployment is claimed. Phone/mount/domain diversity and independent road reference remain physical validation work.

## Judge demo

Open DEMO, confirm `NOT LIVE`, run Quick Synthetic, show GNSS → tunnel → continuing IDR marker/uncertainty → bounded recovery, then switch to Public Benchmark for the labelled comparison. If GNSS/internet is unavailable indoors, remain in DEMO and never represent replay as live.
