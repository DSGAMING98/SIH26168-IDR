# Final evidence table

| Evidence | Final value | Scope |
|---|---:|---|
| Runtime input target | ~10 Hz | Causal Android normalized stream |
| Physical normalized stream | ~9.6 Hz | Existing Phase 9.1 phone evidence |
| Physical native IMU | ~50 Hz | Existing Phase 9.1 phone evidence |
| Android engine throughput | 11,545 samples/s | Warm host JVM engine-only |
| Android engine average | 0.0866 ms/sample | Excludes sensors/UI/logging/startup/power |
| Android engine P95 | 0.185 ms/sample | Same scope |
| Frozen GRU | 4,257 parameters | Pure Kotlin, OOD gated |
| Public S1 60 s Hybrid | 74.192 m / 28.232% | 262.794 m named stop/go holdout |
| Public S1 60 s Raw | 327.185 m | Same evaluator-only holdout |
| Phase 11 stationary 30/60/120 s | 0.000112 / 0.000154 / 0.000158 m | Host deterministic regression |
| APK size/hash | See `FINAL_BUILD_MANIFEST.json` | Generated after final commit/tag |
| Test totals | See `FINAL_BUILD_MANIFEST.json` | Generated after final verification |
