# Phase 7: causal GNSS loss detection and smooth reacquisition

## Runtime boundary

`run_phase7_runtime` accepts a Phase 2 `RuntimeDataset`, frozen Phase 4/5/6 components, a blackout window, and Phase 7 settings. It has no VBOX/reference, future-sample, route, destination, scenario-ID, or benchmark-truth input. The engine processes exactly one timestamped `NavigationInput` at a time. VBOX enters only `evaluate_phase7_runtime`, after the runtime trajectory is complete.

During blackout, Phase 2 omits every phone GNSS-derived field. Phase 5 remains warm from accelerometer, gravity, gyroscope, magnetometer, and Android sensor orientation. Frozen Phase 6 supplies the blackout position. After blackout, the GNSS tracker receives only the current phone solution and its retained past state.

## GNSS freshness and health

A row is `NO_GNSS` when every navigation field is absent, `INVALID` when the solution is partial/non-finite or violates coordinate, 0-55 m/s speed, 0-360 degree course, or 0-50 m accuracy bounds, and `REPEATED` when it remains within every tolerance below. A complete valid observation is `FRESH` if, relative to the last genuinely fresh solution, at least one changes by more than:

- horizontal position: 0.5 m (spherical haversine distance)
- speed: 0.25 m/s
- wrapped course: 2 degrees
- altitude: 0.5 m

Accuracy and `satellites_in_range` are available validation/diagnostic fields, but changes in those fields alone do not imply a new navigation solution. This is essential because S1 logger rows are near 10 Hz while the observed navigation-solution change cadence is roughly 9 seconds median.

## State machine

- `GNSS_ACTIVE`: fresh GNSS is usable. Three seconds without a genuinely fresh fix enters `GNSS_DEGRADED`.
- `GNSS_DEGRADED`: a fresh fix returns directly to active; two seconds of absent/invalid GNSS or 15 seconds since the last fresh solution enters `IDR_ACTIVE`.
- `IDR_ACTIVE`: Phase 5 plus frozen Phase 6 supplies navigation. The first fresh returned fix starts `GNSS_VERIFYING` but applies no correction.
- `GNSS_VERIFYING`: requires two genuinely fresh, mutually consistent fixes. A gap above 20 seconds or two seconds of renewed loss returns to IDR.
- `GNSS_RECOVERING`: valid fresh fixes update a correction target. Renewed GNSS loss returns to IDR; bounded convergence followed by at least six seconds returns to active.

Candidate consistency limits implied displacement and reported speed to 55 m/s, wrapped course rate to 120 degrees/s, and course-versus-motion bearing residual to 80 degrees once displacement exceeds 3 m. The innovation gate is `max(25 m, 3*hypot(IDR horizontal sigma, GNSS accuracy))`. It is recorded for diagnosis rather than used as a permanent veto: multiple physically consistent fixes can be accepted after large legitimate IDR drift.

## Smooth fusion

At verification, the local GNSS-minus-navigation offset becomes an uncertainty-weighted target. Gain is `IDR_variance / (IDR_variance + GNSS_accuracy^2)`, clamped to 0.15-0.85. Trust ramps over three seconds. Offset convergence is exponential with a three-second time constant and each update is capped at 10 m/s. The navigation state itself changes smoothly; this is not a display-only animation.

B0 snaps to the first returned coordinate even if stored. B1 waits for the first genuinely fresh fix and then snaps. P7 waits for consistency and applies the bounded correction. Across the six holdouts B1 jumps 13.453-563.128 m; P7's largest individual update is 1.010-1.050 m.

## Development freeze and evaluation

The full development spans `[1070,1210)`, `[1940,2090)`, and `[3790,3930)` are outside all six quarantine regions. `FAST_TWO_FIX` reduced development recovery time and post-reacquisition RMSE versus both three-fix profiles while retaining synthetic isolated-outlier rejection. `configs/phase7/io_vnbd_s1_phase7.json` was then marked frozen before one held-out pass.

Post-reacquisition RMSE/P95 are absolute VBOX evaluation errors beginning when verified recovery starts. They include the known phone-GNSS/VBOX absolute offset and should not be confused with blackout-relative drift. Phase 7 preserves every original Phase 6 blackout result and makes no claim that reacquisition fixes the error accumulated before GNSS returns.

## Performance and limitations

On `S1_60_STOP_GO`, warm Phase 5, frozen Phase 6, and Phase 7 processing conservatively measures 19.29 ms/sample or 51.83 samples/s. The incremental state/fusion step is 0.075 ms average, 0.073 ms P50, 0.135 ms P95, and 0.218 ms P99. Loading, model/map loading, road localization/spatial-index construction, VBOX evaluation, serialization, and plotting are excluded.

The evidence is one journey and one phone logger. GNSS accuracy is a scalar, covariance is heuristic, course may be weak at low speed, and post-tail ACTIVE/DEGRADED cycling reflects S1's sparse genuine-fix cadence. Phase 5/6 travelled-distance, heading, and wrong-road failures remain. Cross-device/dataset validation is required before treating thresholds as general.
