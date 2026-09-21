# Phase 10 judge summary

Phase 10 delivers a standalone Android intelligent dead-reckoning prototype rather than a sensor logger. The existing causal 10 Hz phone stream feeds an on-device six-state EKF, vehicle-frame alignment, stationary/ZUPT logic, an exact pure-Kotlin port of the frozen 4,257-parameter Phase 5 GRU, and OOD protection. During simulated loss, runtime GNSS is null and the engine contains a second defensive rejection boundary; no reference, future fix, route, destination, road map, laptop, cloud service, or API key is available to the estimator.

The navigation UI separates LIVE, explicitly synthetic DEMO REPLAY, and detailed diagnostics. An offline local trajectory canvas shows GNSS/IDR/recovery state, current marker, heading, scale, north and uncertainty. GNSS return requires two distinct fresh fixes and uses a bounded 5 m/s reconciliation rather than teleporting.

## Deterministic evidence

- Synthetic story: 6 s GNSS + 10 s blackout + 11 s reacquisition, ending `GNSS_ACTIVE`.
- Blackout propagation: 59.991 m; no runtime GNSS rows/fixes in the blackout fixture.
- Moving-engine fixture: 23.501 m propagation over 2.9 s; uncertainty 1.153 -> 2.687 m.
- Stationary fixture: 0.0 m/s final speed and approximately 4.4e-8 m displacement.
- Recovery fixture: 8.338 m initial innovation, 0.5 m maximum step correction, 0.080 m final error, final `GNSS_ACTIVE`.
- Pure-Kotlin GRU parity: three Python golden windows pass at residual tolerance `1e-4` m/s and OOD tolerance `1e-5`; parameter count 4,257.
- Isolated warm JVM engine microbenchmark: 3,471 samples/s, 0.288 ms/sample average, 0.899 ms/sample P95. This excludes Android rendering, sensors, logging, startup, and device power/thermal effects.
- Regression: 30/30 Kotlin/JVM tests and 212/212 Python tests pass; debug APK builds offline.

## Honest boundary

No emulator/phone UI rendering or Phase 10 physical drive was performed by the development environment. This phase does not claim road-map matching, real-road error, calibrated uncertainty, battery/endurance results, or universal <10% drift. Those are physical Phase 11 validation tasks. The included demo is prominently synthetic and uses the same engine without a planned route or hidden reference.
