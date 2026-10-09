# NavGhost 2.4.0 release status

- versionName: 2.4.0; versionCode: 41.
- Change: tested generic inertial-input/replay adapter and Android forwarding adapter.
- Existing runtime estimator/model remains unchanged. Offline heading experiments are NOT deployed.
- Host gates before device validation: 293 Python tests, 194 Kotlin tests, Android lint, debug and signed release builds passed.
- Signing certificate matches the previously published 2.4.0 certificate.
- Protected public APK SHA-256: `cc1066ae3ba073fe657564624b2152ba67a3812eb5dcc4b4ac50bfa5808ff1fd`.
- The website download is pinned to this exact filename and hash; rejected research estimators were not published.
- In-place upgrade passed on a vivo V2513 running Android 16; app data and original install time were preserved.
- Splash/main launch, all six primary screens, sensor availability, permission state and tunnel safety gating were checked on-device. Android's crash buffer remained empty.
- Repeat verification on 2026-10-06 passed 25/25 focused metro stop/resume, speed-bound, timing and recovery tests, followed by the full 194/194 Android suite. The same signed APK was installed in place and its device-side SHA-256 matched the release artifact.
- Moving and lane-level accuracy remain separate evidence requirements.

Full stationary results and their limits are in [Android device verification](technical-evidence/finalist_20261005/ANDROID_DEVICE_VERIFICATION.md).
