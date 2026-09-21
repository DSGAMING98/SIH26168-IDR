# NavGhost 2.4.0 compliance engineering release

NavGhost 2.4.0 closes two implementation gaps identified during the SIH portal audit without
changing the frozen Android GRU weights or weakening the GNSS isolation boundary.

## Android motion conditioning

The Android sensor conditioner now applies a causal median/MAD transient guard before its existing
low-pass stage. Isolated pothole and mount-shock impulses are bounded, while normal braking and
sustained acceleration remain observable. Regression tests cover impulse rejection, sustained
motion and reset behavior.

## External-IMU edge runtime

The new hardware-neutral edge runtime accepts calibrated IMU data at native rates, including
200 Hz, with configurable mounting axes, forward-only non-holonomic propagation, stationary bias
learning, bounded ML speed-correction hooks, GNSS updates and optional offline road constraints.
See `docs/EXTERNAL_IMU_EDGE_ENGINE.md`.

## Evidence boundary

This release does not relabel the existing IO-VNBD results. The current frozen phone estimator does
not support a universal sub-10-percent drift claim, and physical FOG accuracy has not been measured
without FOG hardware and an independent reference. The website reports the verified software input
rate and keeps those physical accuracy claims explicit.
