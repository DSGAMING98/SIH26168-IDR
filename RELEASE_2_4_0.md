# NavGhost 2.4.0 release status

- versionName: 2.4.0; versionCode: 41.
- Latest navigation update: completed route geometry now disappears behind the live vehicle marker, destination suggestions collapse after selection, and Go search combines native Google Places with OpenStreetMap and exact-coordinate fallbacks.
- Existing runtime estimator/model remains unchanged. Offline heading experiments are NOT deployed.
- Current Android gates: 214 Kotlin tests, Android lint, focused navigation tests and the signed release build passed.
- Signing certificate matches the previously published 2.4.0 certificate.
- Current public APK: [`NavGhost-v2.4.0-Go-Navigation-Fix-release.apk`](technical-evidence/releases/NavGhost-v2.4.0-Go-Navigation-Fix-release.apk).
- Current public APK SHA-256: `b9924f48057fd9576ff9a650da1a8d87c256480913f7f5c013b8ae5defbde8f6`.
- The production website download is pinned to this exact build and hash; rejected research estimators were not published.
- In-place upgrade passed on a vivo V2513 running Android 16; app data and original install time were preserved.
- Splash/main launch, all six primary screens, sensor availability, permission state and tunnel safety gating were checked on-device. Android's crash buffer remained empty.
- Repeat verification on 2026-10-06 passed 25/25 focused metro stop/resume, speed-bound, timing and recovery tests, followed by the full 194/194 Android suite. The same signed APK was installed in place and its device-side SHA-256 matched the release artifact.
- On 2026-10-24, the navigation-fixed release installed in place on the same vivo device without clearing data. Native place search and destination-panel dismissal were verified on-device with no crash or ANR. Route-progress trimming is covered by deterministic unit tests; a moving-road confirmation remains required.
- Moving and lane-level accuracy remain separate evidence requirements.

Full stationary results and their limits are in [Android device verification](technical-evidence/finalist_20261005/ANDROID_DEVICE_VERIFICATION.md).
