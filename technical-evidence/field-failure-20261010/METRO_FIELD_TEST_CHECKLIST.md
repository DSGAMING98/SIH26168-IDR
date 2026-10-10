# NavGhost Controlled Metro Field-Test Checklist

## Pass/fail criteria fixed before the run

- App remains responsive; no crash or ANR.
- No exact speed is shown once IDR uncertainty reaches +/-100 m.
- No precise map arrow is shown once IDR uncertainty reaches +/-500 m.
- No uncorrected-speed plateau above the candidate safety envelope.
- A real stop is not declared from one quiet interval.
- On return to open sky, three distinct consistent accurate fixes enter recovery.
- A large-drift state returns near those verified fixes promptly, not after minutes of
  fixed-rate crawling.
- One isolated/stale/inconsistent fix cannot relocate the estimate.
- Manual pan/zoom pauses follow; the map does not force recenter until RECENTER is tapped.
- 3D, Google Legacy, and Google 3D can each be selected repeatedly without losing the
  shared navigation snapshot. A failed online renderer falls back visibly.

## Before departure

1. Preserve the protected APK and current app data.
2. Install the candidate in place with `adb install -r`; do not clear storage.
3. Record package version, signing certificate, APK SHA-256, phone model, Android version,
   and battery level.
4. Start one continuous screen recording with the status-bar clock visible.
5. Start NavGhost logging at ground level and wait for a stable accurate GNSS position.
6. Start an independent reference recording (for example, a second GNSS logger above
   ground plus station-arrival timestamps). Do not feed it into NavGhost.
7. Record a spoken or written time marker visible to both recordings.

## During the route

1. Record tunnel entrance time and the last trustworthy GNSS state.
2. At every station, record arrival, complete stop, departure, and platform/station name.
3. Do not infer a stop from NavGhost; record it independently.
4. Capture speed, mode, used satellites, uncertainty, and map position at each event.
5. Switch through all three map modes at pre-declared times; pan/zoom each mode and verify
   follow remains paused until RECENTER.
6. Do not stop navigation after the third station; continue through the planned open-sky exit.

## Reacquisition

1. Record the first fresh callback, first verifying state, recovering state, and active state.
2. Record reported accuracy and the independent reference position.
3. Verify that no single outlier relocates the marker.
4. Verify that a verified large-drift recovery returns promptly and that uncertainty shrinks.

## End of run

1. Say or display an explicit journey-end marker before stopping the logger.
2. Stop NavGhost immediately after that marker.
3. Export the session once; do not edit the ZIP.
4. Preserve the original screen recording, reference recording, and ZIP; hash all files.
5. Report journey-only, post-journey (if any), and full-session metrics separately.

## Required result labels

- `PASS`: criterion measured and satisfied.
- `FAIL`: criterion measured and not satisfied.
- `NOT MEASURED`: evidence missing.
- Never convert `NOT MEASURED` into `PASS`.
