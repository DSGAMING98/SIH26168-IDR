# NavGhost final technical overview

## Purpose

SIH26168 is a phone-only localization system for the period when GNSS itself is unavailable or unreliable. Offline maps solve a different problem: they can display cached roads while GNSS still supplies position. This project keeps estimating the vehicle position from Android inertial sensors, a classical EKF, and a safety-gated frozen GRU, then reconciles smoothly when GNSS returns.

> We are not predicting where the vehicle should be. We are estimating where the vehicle is.

No OBD-II, wheel sensor, external IMU, custom hardware, account, cloud inference, backend, or planned route is required.

## Final architecture

![Runtime and evaluation architecture](assets/phase12_architecture.svg)

Android sensor timestamps and GPS callbacks share the elapsed-realtime clock. A causal 10 Hz synchronizer selects only sensor values at or before each runtime timestamp. `GPS_PROVIDER` is the sole physical location source. During simulated loss, the runtime fix is null even if raw callbacks continue into the evaluator log.

The live estimator performs conditioning, gravity removal, vehicle-direction alignment, six-state EKF propagation, stationary/ZUPT handling, and an optional GRU speed-residual measurement. The 4,257-parameter GRU does not predict position. Soft OOD raises measurement variance; hard OOD rejects the correction and displays `AI SAFETY FALLBACK`.

The `MapProvider` API returns only visual presentation metadata. It cannot return a marker or location. NavGhost can render the engine-owned marker and state-colored path over the official Google Maps SDK, but Google My Location is disabled and no Google location/fused provider exists in the app. A credential-free local ENU view is the guaranteed fallback. Phase 6 map matching remains research-only because it improved only two of six frozen cases; Google road tiles are not map matching and never alter engine state.

## State and safety behavior

![Localization state machine](assets/phase12_state_machine.svg)

- Before a trusted fix: `WAITING_FOR_GNSS`.
- With GNSS but before vehicle alignment: `CALIBRATING`.
- Loss before alignment: `CALIBRATION_REQUIRED`; speed and position hold while uncertainty grows.
- Trusted GNSS: `GNSS_ACTIVE`.
- Loss after alignment: `IDR_ACTIVE`; GNSS is absent from runtime.
- Return: two distinct fresh fixes, `GNSS_VERIFYING`, then bounded `GNSS_RECOVERING`, then `GNSS_ACTIVE`.
- New loss during recovery safely returns to IDR.

The final marker always comes from `IdrEngine`: GNSS/EKF while trusted, EKF/IDR during denial. It never comes from map context, a route, a public replay reference, raw hidden GNSS, or a network provider.

## Evidence by phase

| Phase | Commit | Engineering result |
|---|---|---|
| 1 | `bcebc9c` | Validated synchronized 51,746-row S1 phone/VBOX session. |
| 2 | `f6e367b` | Deterministic, leakage-safe blackout harness and metrics. |
| 3 | `1f8644e` | Honest raw inertial baseline. |
| 4 | `1461f64` | Calibrated, motion-aware classical DR. |
| 5 | `39b50c1` | Six-state EKF plus frozen OOD-gated GRU residual. |
| 6 | `da45078` | Experimental probabilistic road matching; mixed results retained. |
| 7 | `93ddc6b` | Freshness verification and bounded reacquisition. |
| 8 | `7dd4a1d` | Frozen zero-shot cross-device/location validation; moderate generalization. |
| 9/9.1 | `4077378`, `e039ec7` | Android logger, real sensor acquisition, first-fix and masking observability. |
| 10 | `0fba068` | Standalone on-device Android estimator and Kotlin GRU parity. |
| 11 | `a0eadec` | Stationary/alignment hardening, field test, validator, product UI. |
| 12 | `sih26168-final` | Competition identity, isolated map provider, quick/public demos, final evidence and bundle. |
| Release polish | `navghost-release` | NavGhost identity, premium map-first UI, optional official Google visual canvas, fallback and release hardening. |

## Selected measured evidence

The public replay uses the pre-existing `S1_60_STOP_GO` 60-second holdout. Reference travel is 262.794 m. Raw DR final error is 327.185 m; frozen Phase 5 Hybrid final error is 74.192 m (28.232% drift). This is labelled by scenario and is not a universal accuracy claim. The strongest single frozen holdout was the preselected 75-second surprise window at 3.855% Phase 5 drift, but that one result does not prove generalization.

Across the 10/30/60/120-second standards, Phase 5 Hybrid drift was 22.655%, 18.571%, 28.232%, and 38.480%. Phase 8 found moderate cross-device/location generalization: Hybrid improved EKF once and degraded it twice on three moving windows, with hard-OOD updates safely skipped.

Phase 11 engine-only JVM throughput was 11,545 samples/s, 0.0866 ms average and 0.185 ms P95 versus a 10 Hz input. This excludes Android rendering, sensor acquisition, logging, startup and power effects. The conservative Phase 5+6+7 research pipeline measured 51.83 samples/s.

## Physical Android evidence

The existing Phase 9.1 phone run verified approximately 50 Hz native IMU, approximately 9.6 Hz normalized runtime, 60 visible/5 used satellites, first valid fix in 19.17 s, physical GPS callbacks, and a real fresh fix masked from runtime during simulated loss. It verifies acquisition and isolation plumbing, not road accuracy. Phase 11 was reported working on the physical phone, but no new private trace is committed.

## Final application

The Android app is **NavGhost — Navigation Beyond GNSS**, package `org.sih26168.idrlogger`, version 1.1.0. LIVE is a map-dominant real runtime with engine-owned marker/halo/path, follow/recenter, heading/north-up, optional satellite view, compact state telemetry, and safe controls. DEMO is always marked NOT LIVE and contains a 27-second deterministic synthetic story plus an evaluator-only public benchmark comparison. SYSTEM exposes sensor, GNSS, localization, AI/OOD, field test, session, performance and map health. Logs stay app-private until explicit ZIP export.

## Limitations

- No universal `<10%` drift claim: long or strongly shifted conditions remain difficult.
- Live uncertainty is covariance-derived engineering uncertainty, not a calibrated 95% confidence region.
- Google road/satellite context requires a locally configured, restricted key and network; local ENU remains guaranteed.
- The Maps SDK does not expose an authentication-failure callback, so the layer control provides an explicit LOCAL fallback if a configured key is rejected.
- No new survey-grade, RTK, battery-endurance, or cross-phone road result was produced in release polish.
- Vehicle alignment needs a short, safe straight movement; before alignment, blackout is intentionally held rather than fabricated.
- Magnetometer disturbance and unfamiliar phone/mount domains can disable ML assistance.

The remaining validation work is physical only: safe passenger-operated road runs, optional independent reference, thermal/battery endurance, and judge feedback.
