# Android device verification — NavGhost 2.4.0

Date: 2026-10-05

Device: vivo V2513

Android: 16 (API 36)

Package: `org.sih26168.idrlogger`

Artifact: `NavGhost-Android-v2.4.0.apk`

## Upgrade and identity

- Installed with Android's in-place upgrade path; app data was not cleared.
- `versionName` is 2.4.0 and `versionCode` is 41.
- The original install time and application data directory were preserved.
- APK SHA-256: `c0f0ff3e4551e242f90d9b900ec6e7cc77d66d16108c71c60290fd5e9d4deaed`.
- Signing-certificate SHA-256: `638d559143fa28181e3b498157706b3a087cbe18144560e3650281c66c99f281`; this matches the previously published 2.4.0 certificate.

## Stationary checks completed

- Splash and main activity launched successfully.
- Three additional cold launches completed in 253 ms, 295 ms and 312 ms (`am start -W` total time).
- Core 3D, turn-by-turn, dashboard, nearby, trip-history and insights screens rendered and remained responsive.
- Google map presentation and local ENU fallback were both present.
- Precise/coarse location and notification permissions were granted.
- The phone exposes accelerometer, calibrated and uncalibrated gyroscope, magnetic-field, linear-acceleration and rotation-vector sensors.
- The tunnel-test control correctly rejected activation before live navigation prerequisites, rather than representing an unvalidated blackout as active.
- Android's crash buffer remained empty after upgrade, launch, tab navigation and repeated cold launches.

## Runtime footprint

- Final observed total PSS: 90,229 KB; total RSS: 212,852 KB.
- In a short post-navigation frame sample, Android reported 245 rendered frames, 1 janky frame under the current metric (0.41%), with 10/26/27/57 ms at P50/P90/P95/P99.
- These are short stationary observations on one device, not battery, thermal, route, estimator-latency or moving-accuracy measurements.

## Boundaries

Indoor stationary testing did not obtain the evidence needed to claim a trusted outdoor GNSS fix, a real moving blackout, moving recovery accuracy, road/lane accuracy, or under-10% drift on the phone. No private phone trace or screenshot containing saved-trip coordinates is published.

**MOVING VEHICLE VALIDATION REQUIRED**
