# NavGhost release-readiness update — 2026-10-09

## Measured acceptance result

| GNSS-denied window | Protected estimator drift | Under 10% |
|---:|---:|:---:|
| 10 s | 8.503% | yes |
| 30 s | 2.834% | yes |
| 60 s | 3.765% | yes |
| 120 s | 11.692% | no |

**Verified result: 3/4.** NavGhost does not claim that the four-window requirement has been met.

## Additional candidates evaluated

A drive-disjoint causal outage-boundary speed estimator improved development and holdout speed error, but its frozen four-window result was 24.548%, 7.526%, 5.106%, and 11.505%. It was rejected and was not ported to the Android release.

The existing road-heading candidate was also revalidated after fixing ambiguous-road and disconnected-transition behavior. Development improved, but a non-standard 75-second holdout regressed from 40.628% to 65.917%. It was rejected before the four target windows were opened.

These failures are retained because they establish an important limit: an inferred road direction is not a universally reliable velocity observation, and improved outage-entry speed alone cannot observe later constant-speed changes during total GNSS denial.

## Verification and publication

- Python: 311 passed.
- Kotlin/JVM: 204 passed.
- Android lint: passed.
- Android debug build: passed.
- Website build: passed.
- Protected public APK SHA-256: `cc1066ae3ba073fe657564624b2152ba67a3812eb5dcc4b4ac50bfa5808ff1fd`.
- Original frozen GRU SHA-256: `fa2169781f9e499dd87fdd00038a3b4a1326181b31938cec237a7802ae0bb4ec`.
- Focused GRU SHA-256: `e548cac929ae78c0a6449f8bb6d0cecd772166ae0fcaf140bb1a096d4055a2c1`.

The live website now pins the primary Android download to the protected artifact by exact filename and SHA-256. Rejected accuracy candidates and a later host-only debug build are not published as production APKs.

## Remaining limitation

The 120-second window still exceeds the target by 1.692 percentage points. During complete satellite denial, a phone IMU cannot distinguish rest from sufficiently smooth constant-speed motion without an additional credible observation. A true 4/4 claim therefore requires new independent information—such as wheel/vehicle speed, validated visual-inertial odometry, or a rail/road constraint proven on untouched routes—and a new untouched acceptance set.
