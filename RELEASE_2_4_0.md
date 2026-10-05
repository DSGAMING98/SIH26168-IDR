# NavGhost 2.4.0 release status

- versionName: 2.4.0; versionCode: 41.
- Change: tested generic inertial-input/replay adapter and Android forwarding adapter.
- Existing runtime estimator/model remains unchanged. Offline heading experiments are NOT deployed.
- Host gates before device validation: 293 Python tests, 194 Kotlin tests, Android lint, debug and signed release builds passed.
- Signing certificate matches the previously published 2.4.0 certificate.
- Final APK SHA-256: `c0f0ff3e4551e242f90d9b900ec6e7cc77d66d16108c71c60290fd5e9d4deaed`.
- In-place upgrade passed on a vivo V2513 running Android 16; app data and original install time were preserved.
- Splash/main launch, all six primary screens, sensor availability, permission state and tunnel safety gating were checked on-device. Android's crash buffer remained empty.
- Moving and lane-level accuracy remain separate evidence requirements.

Full stationary results and their limits are in [Android device verification](technical-evidence/finalist_20261005/ANDROID_DEVICE_VERIFICATION.md).
