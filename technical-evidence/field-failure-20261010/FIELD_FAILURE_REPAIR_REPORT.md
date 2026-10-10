# NavGhost Field-Failure Repair Report

Date: 2026-10-10

Candidate: NavGhost 2.4.0 field-recovery candidate

Decision: **READY FOR CONTROLLED FIELD TESTING**

This is not a production release and has not yet repeated the Bengaluru Metro trip.

## Root causes and repair status

| Failure | Evidence and root cause | Repair status |
|---|---|---|
| 121 km/h through stops | The last trusted GNSS speed was 18.603605 m/s. The engine added biased acceleration until it reached exactly the configured `last speed + 15 m/s` ceiling: 33.603605 m/s or 120.97 km/h. It remained there during classifier-reported stationary intervals. | The unobserved increase allowance is reduced from 15 to 5 m/s and the minimum uncorrected ceiling from 25 to 15 m/s. Exact field replay no longer reaches 33.60 m/s; journey maximum is 23.819 m/s (85.75 km/h). Exact station-stop speed remains unobservable from a quiet phone IMU alone and needs a new field run. |
| Large position drift | The false speed and uncorrected yaw were propagated for a 490.993 s callback gap. Uncertainty reached 17,566.84 m. | Runaway speed is bounded earlier. At +/-100 m the UI no longer presents an exact speed; at +/-500 m every map mode suppresses the precise arrow and declares position unavailable. Underground absolute position is still an estimate, not a verified fix. |
| GNSS did not recover at the journey endpoint | Credible callbacks returned near elapsed 614.543 s, but the old policy nudged a multi-kilometre error at only 5 m/s. It did not reach `GNSS_ACTIVE` until elapsed 1,510.616 s, in post-journey recording. | Recovery now requires three distinct, mutually consistent, accurate callbacks. For a long, high-uncertainty, >100 m innovation it explicitly re-anchors position covariance; one stale/outlier fix cannot teleport it. Exact replay corrects a 5,115.57 m innovation and returns within about 20.42 m of the consistent fixes on the third callback. |
| Position jump when GNSS first returned | Absolute phone/alignment heading was applied before reacquisition verification and could alter correlated EKF position states. | Heading correction is deferred while in IDR, verifying, or recovering. It is accepted through the verified recovery path instead. |
| 61-62 satellites but zero used | Telemetry shows no usable Android location callbacks during the main gap. Satellite visibility was diagnostic only and did not drive the state machine. | No satellite-count threshold was added. Transitions continue to require a fresh, credible physical location callback. |
| Custom 3D freeze | Supplied logs contain no renderer lifecycle/error telemetry. The videos and code do not establish whether the map surface froze, its data became stale, or remote tiles failed. | Existing renderer lifecycle, manual follow/recenter, network gates, and fallback tests pass. No unproven renderer rewrite was made. Long physical mode-switch testing remains required. |

## Journey-only and full-session results

The exact journey endpoint cannot be synchronized to sub-second precision. The
screen recording is aligned to approximately session elapsed 95-614 seconds, with
several seconds of uncertainty. No later data is silently discarded.

### Journey/video-bounded

- Original app: repeated 114-121 km/h display, including `STATIONARY` plus 121 km/h.
- Original uncertainty: approximately +/-5.6 m to more than +/-14 km on screen.
- Candidate offline replay maximum: 23.819272995 m/s (85.749 km/h).
- Candidate state at the video boundary: IDR active; no claim of trustworthy absolute
  underground position is made.

### Post-journey / endpoint-uncertain

- First fresh fix after the main outage: elapsed 614.543 s.
- Candidate: after the third mutually consistent distinct callback, large-drift
  position is re-anchored within approximately 20.42 m of the first returned fix.
- This replay is not a physical confirmation that the user was at the GNSS fix.

### Full original export

- Duration: 8,928.972 s.
- Original app eventually reached `GNSS_ACTIVE` at elapsed 1,510.616 s.
- This late post-journey recovery is retained as evidence but is not used to negate
  the failure recorded during the metro journey.

## Regression evidence

### Frozen laboratory acceptance (policy unchanged)

| Window | Protected/candidate drift | Gate |
|---|---:|---|
| 10 s | 8.503408% | PASS |
| 30 s | 2.834094% | PASS |
| 60 s | 3.764776% | PASS |
| 120 s | 11.691986% | **FAIL** |

Result remains **3/4**. No 4/4 claim is made.

### Automated checks

- Python: 311 passed, 2 dependency deprecation warnings.
- Android JVM: 207 passed, 0 failed, 0 skipped.
- Focused real-export replay: passed.
- Android lint: passed.
- Debug assembly: passed.
- Frozen Phase 5 GRU SHA-256:
  `fa2169781f9e499dd87fdd00038a3b4a1326181b31938cec237a7802ae0bb4ec`

## Candidate artifact

- APK: `candidate/NavGhost-2.4.0-field-recovery-candidate-release.apk`
- SHA-256: `00ff90ac028188ef41214e0f876ad2baafa204857bd591071ad74dcd61a7aeeb`
- Package: `org.sih26168.idrlogger`
- Version name/code: `2.4.0` / `41`
- Signing: NavGhost competition certificate; APK Signature Schemes v2 and v3.
- Signing-certificate SHA-256:
  `638d559143fa28181e3b498157706b3a087cbe18144560e3650281c66c99f281`
- Status: **FIELD-VALIDATION REQUIRED**

The protected website APK has not been overwritten.

## Readiness classification

### Demonstrated and verified offline

- Exact exported-session replay.
- Removal of the 121 km/h ceiling failure in that replay.
- Three-fix consistency gate and large-drift re-anchor.
- Outlier streak reset and stale-callback identity protection.
- Uncertainty-driven speed/marker suppression.
- Existing renderer fallback and camera-policy regression tests.

### Verified on the physical phone

- Installed in place with `adb install -r`; app data was not cleared.
- Package version and signing identity remained continuous.
- High-accuracy physical GNSS callbacks arrived at approximately 1 Hz.
- Accelerometer, gyroscope, rotation-vector, gravity, and magnetometer subscriptions
  were active at the requested 50 Hz sampling period.
- MapLibre 3D, Google Legacy, and Google 3D/Hybrid all rendered successfully in the
  short smoke test.
- A manual map drag remained under user control; explicit `RECENTER` restored the
  live position view.
- Stopping navigation removed the GNSS registration and stopped the foreground
  service; no NavGhost fatal exception or ANR was found in the collected log.

### Implemented but not field-verified

- Physical large-drift GNSS reacquisition on the recorded phone.
- Long-session transitions among 3D, Google Legacy, and Google 3D.
- Stop/dwell/restart behavior on a real metro journey.

### Known limitations

- A phone IMU alone cannot observe absolute constant velocity or distinguish perfect
  smooth cruise from rest. Exact underground stops require transition evidence or an
  independent constraint; the app now avoids presenting unsupported precision.
- The 120-second frozen accuracy window remains at 11.692%, so the 4/4 target is not met.
- The original journey lacks an independently synchronized position reference.

### Release blocker

- The physical-device smoke test is complete. A new controlled metro validation run
  is still required before this candidate can be called a field-validated replacement
  for the protected public APK.
