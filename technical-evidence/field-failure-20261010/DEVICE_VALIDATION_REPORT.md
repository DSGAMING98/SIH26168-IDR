# NavGhost Physical-Device Validation

Date: 2026-10-10

Device: vivo V2513 / V2513i, Android 16

ADB serial: `10BFAB14ED0026H`

Candidate: NavGhost 2.4.0 (`versionCode 41`)

## Installation and identity

- Installed in place with Android's replace-install operation.
- Application data was not cleared.
- `firstInstallTime` remained unchanged.
- Signed APK SHA-256:
  `00ff90ac028188ef41214e0f876ad2baafa204857bd591071ad74dcd61a7aeeb`
- Signing-certificate SHA-256:
  `638d559143fa28181e3b498157706b3a087cbe18144560e3650281c66c99f281`
- The pre-install APK was preserved as
  `candidate/installed-before-field-recovery-base.apk` with SHA-256
  `cc1066ae3ba073fe657564624b2152ba67a3812eb5dcc4b4ac50bfa5808ff1fd`.

## Runtime checks

- Splash and main screen launched successfully.
- Foreground navigation service entered the foreground while recording.
- Physical accelerometer, gyroscope, rotation-vector, gravity, and magnetometer
  listeners were registered at the app's requested 50 Hz sampling period.
- The high-accuracy GNSS listener was registered and delivered fresh fixes at
  approximately 1 Hz when sky exposure was available.
- Stationary display remained at `0 km/h`; stationary testing cannot validate metro
  stop/restart behavior or long underground propagation.

## Map checks

- MapLibre 3D rendered and showed the physical fix.
- Google Legacy rendered and showed the physical fix.
- Google 3D/Hybrid rendered buildings and the physical fix.
- Manual dragging moved the map without automatic snap-back.
- Explicit `RECENTER` returned the map to the live marker.

Evidence screenshots are stored in `candidate/device-ui-*.png`.

## Shutdown and stability

- `STOP NAVIGATION` changed the service from `startRequested=true` to
  `startRequested=false` and removed foreground status.
- Android location diagnostics recorded removal of NavGhost's GNSS registration at
  19:23:28 local time.
- No `FATAL EXCEPTION`, NavGhost ANR, or NavGhost process crash was present in the
  collected logcat window.

## Decision

**PASS — PHYSICAL-DEVICE SMOKE TEST**

This is not a metro field-validation pass. A controlled journey with synchronized
station timestamps and a trustworthy reference is still required to validate
stop/dwell/restart behavior, long-outage drift, and physical GNSS reacquisition.
