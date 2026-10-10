# NavGhost 2026-10-10 Field-Failure Baseline

Status: pre-repair evidence checkpoint. This document separates direct observations,
user-reported field observations, confirmed code/data findings, and hypotheses. It
does not treat the full exported recording as continuous underground travel.

## Evidence preservation

The original files remain in their original Desktop locations and were not edited.
The ZIP contents were mechanically extracted under `raw/` for analysis.

| Original | SHA-256 |
|---|---|
| `WhatsApp Video 2026-10-10 at 17.41.25.mp4` | `c61655789644b25bea128462b911f4d7c6c93c134e963bcb7e0d59610f4bb028` |
| `WhatsApp Video 2026-10-10 at 17.42.48.mp4` | `0b792c8ab60e20a8a06fdd869850c86d5a52b55d0d23e42a3e72a57983b2b7d7` |
| `export session 1.zip` | `d76b78a766a6056686d3274c7f327bc5cb5df07d10dc587a299dd47631fc9a03` |
| `export session 2.zip` | `5cf90278447ab788776a357efd95871012bc5836864e4ebc6d3e6350a1534c94` |

## Time boundaries

### Journey/video-bounded view

- Session 1 starts at 2026-10-10 15:36:23 IST and ends at 18:05:12 IST.
- The underground screen recording is 518.739 seconds long and its first visible
  phone time is approximately 15:38 IST.
- The best evidence-based alignment places the recorded journey at approximately
  session elapsed 95-614 seconds (about 15:37:59-15:46:38 IST).
- This boundary has several seconds of uncertainty because the video supplies a
  minute-resolution status-bar clock, not a shared high-resolution timestamp.
- The final journey frame still shows IDR active. The first fresh post-outage GNSS
  callback occurs at session elapsed 614.543 seconds. The available evidence does
  not establish whether that callback arrived just before or just after the exact
  physical journey endpoint.
- No narrower cutoff is selected because doing so would manufacture precision not
  present in the evidence.

### Post-journey view

- Session 1 continued recording after the metro journey, per the user's correction.
- The interval after approximately elapsed 614 seconds is therefore reported as
  post-journey/endpoint-uncertain data, not underground metro ground truth.
- GNSS recovery observed later in this interval must not be used to deny or dilute
  the journey failure captured by the video.

### Full-session view

- Full exported duration: 8,928.972 seconds (2 h 28 min 48.972 s).
- A final `GNSS_ACTIVE` state is a full-session outcome only.
- The engine did not return to `GNSS_ACTIVE` until elapsed 1,510.616 seconds, about
  14 minutes 56 seconds after the first credible GNSS callback at 614.543 seconds.

## Directly observed in the underground recording

These are on-screen readings, not inferred ground truth:

| Approx. phone time | Displayed state | Displayed speed | Displayed uncertainty |
|---|---:|---:|---:|
| 15:38 | recovering | 25 km/h | +/-5.6 m |
| 15:39 | IDR active | 114 km/h | +/-130.7 m |
| 15:40 | IDR active | 120 km/h | +/-1,313.8 m |
| 15:41 | IDR active, `STATIONARY` | 121 km/h | +/-4,012.3 m |
| 15:42 | IDR active | 118 km/h | +/-6,301.2 m |
| 15:43 | IDR active | 121 km/h | +/-11,178 m |
| 15:44 | IDR active | 121 km/h | +/-14,144.1 m |
| 15:45 | IDR active | 115 km/h | +/-5,439.7 m |
| 15:46 | IDR active | 121 km/h | +/-10,503.9 m |

The map visibly develops a false trajectory and location displacement during this
period. A frame simultaneously showing `STATIONARY` and 121 km/h is direct evidence
that the stop/motion evidence was not being applied to the reported velocity.

## User-reported field observations

These observations are important field evidence but are not converted into precise
coordinates or timestamps that the estimator never received:

- The metro stopped at three stations while NavGhost continued to report about
  121 km/h.
- The user was physically at Mantri Square Sampige Road Metro Station by the end of
  the recorded journey, with improved sky exposure, but NavGhost had not restored a
  trustworthy position.
- Earlier, NavGhost showed an incorrect location around Koramangala while the user
  was physically at Majestic Metro Station.

## Confirmed from exported telemetry and source

### Journey-bounded failure

- The main GNSS callback gap is elapsed 123.550-614.543 seconds: 490.993 seconds.
- The last valid fix before the gap reported speed 18.60360527 m/s.
- The maximum propagated speed is exactly 33.60360527 m/s (120.973 km/h), equal to
  the last trusted speed plus the configured 15 m/s uncorrected-speed allowance.
- There are 3,515 samples at or above 33.5 m/s between elapsed 168.399 and 609.782
  seconds.
- Visible satellites remained around 61-62 while used satellites were zero and no
  usable location callbacks arrived. Satellite visibility did not constitute a fix.
- The motion classifier produced stationary-like intervals while propagated speed
  remained near the ceiling. Notable intervals include 181.366-196.091 s,
  203.187-205.227 s, 261.484-270.027 s, 279.246-280.484 s, and
  307.395-313.051 s. These must not be claimed as exact station-stop matches without
  independent synchronized ground truth.
- Uncertainty reaches 17,566.84 m in the export.

### Post-journey/full-session behavior

- The first fix after the 490.993-second gap is a plausible fix with 7.1 m reported
  accuracy and 1.465 m/s reported speed.
- The state changes to verifying/recovering, but position recovery is rate-limited
  to 5 m/s. With multi-kilometre accumulated error, convergence takes many minutes.
- A second callback gap occurs at elapsed 707.539-800.551 seconds (93.012 seconds).
- `GNSS_ACTIVE` is finally reached at elapsed 1,510.616 seconds. This is later
  post-journey evidence and does not contradict the failure visible in the video.

### Connected failure chain supported by evidence

1. A stale pre-outage velocity seeds propagation.
2. Biased inertial acceleration raises speed to the configured stale-speed ceiling.
3. Stationary-like motion evidence does not reset velocity because the inertial stop
   gate never latches.
4. The false high velocity drives large position drift and covariance growth.
5. Credible GNSS fixes return, but the recovery policy only nudges a multi-kilometre
   error at 5 m/s, delaying restoration for about 15 minutes.

This chain is supported by timestamps, telemetry, and source inspection. It does not
claim that each user-reported station stop is independently timestamped.

## Separate short GNSS-active session

Session 2 lasts 243.840 seconds. It contains short outages and successful recovery:

- GNSS active: 1,853 runtime samples
- IDR active: 214 samples
- Recovering: 160 samples
- Maximum logged speed: 20.126 m/s
- First outage: IDR at 87.299 s, recovering at 102.319 s, active at 110.419 s
- Second outage: IDR at 210.255 s, recovering at 219.316 s, active at 227.580 s

This demonstrates that short, low-drift recovery can work. It does not validate
recovery after the severe underground drift in Session 1.

## Hypotheses requiring repair validation

- Stop detection is too dependent on a signed forward-braking precursor and misses
  real rail stops when phone orientation or measured dynamics do not satisfy it.
- GNSS reacquisition needs a multi-fix consistency gate followed by a bounded,
  covariance-aware re-anchor for large innovations; a fixed 5 m/s nudge is not
  adequate for kilometre-scale drift.
- Heading correction from a newly returned but not-yet-verified fix may alter
  correlated position states before recovery is accepted and should be deferred.
- A renderer freeze in a particular map mode is not proven by the supplied runtime
  telemetry because renderer lifecycle/error events were not logged.

## Baseline conclusion

The journey failure is real and remains visible when the data is bounded to the
recorded metro interval. The improved final state of the much longer export is also
real, but belongs to the post-journey/full-session view. Both are retained; neither
is allowed to overwrite the other.
