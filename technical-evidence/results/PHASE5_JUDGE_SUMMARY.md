# Phase 5 Judge Summary

Phase 3 raw integration drifted because small phone acceleration and orientation errors accumulated twice into position. Phase 4 added gravity alignment, causal conditioning, gyro course, calibration, and conservative motion constraints.

Phase 5 adds a covariance-aware six-state EKF and a 4,257-parameter GRU that predicts only a bounded speed residual. Position is still propagated by the physical EKF. VBOX supplies offline training labels and evaluation only; it is not an estimator input.

All five named holdouts plus the surprise window were quarantined from training, validation, scaling, checkpoint selection, and EKF tuning using 120 seconds before each blackout and 60 seconds after its end.

| Scenario | Raw drift | P4 V4 | P4 V5 | EKF | Hybrid | Hybrid final error | Est. uncertainty |
|---|---:|---:|---:|---:|---:|---:|---:|
| S1_10_STEADY | 8.31% | 21.38% | 19.99% | 21.39% | 22.66% | 34.92 m | 48.43 m |
| S1_30_TURNING | 67.34% | 60.16% | 60.87% | 23.61% | 18.57% | 37.31 m | 44.10 m |
| S1_60_STOP_GO | 124.50% | 82.91% | 83.86% | 36.18% | 28.23% | 74.19 m | 162.37 m |
| S1_120_HIGHER_SPEED | 138.00% | 55.80% | 75.23% | 24.40% | 38.48% | 656.62 m | 2277.73 m |
| S1_45_JUDGE | 100.59% | 61.74% | 61.29% | 52.26% | 52.26% | 118.46 m | 141.19 m |
| S1_PHASE5_SURPRISE | 131.29% | 10.51% | 70.99% | 14.18% | 3.85% | 23.93 m | 451.30 m |

The frozen checkpoint is 21,649 bytes and the complete measured pipeline processed 796.5 samples/s versus a 10 Hz input rate.

The uncertainty is an interpretable covariance-derived estimate (`sqrt(Pxx + Pyy)`), not a statistically calibrated 95% bound. Remaining road-constrained error and single-journey generalization are Phase 6/later limitations; no map matching or Android application is implemented here.
