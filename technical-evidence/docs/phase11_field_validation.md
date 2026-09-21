# Phase 11 field validation protocol

## Safety and purpose

The field-test mode creates repeatable GNSS blackouts without driver interaction. Configure it only while parked. Securely mount the phone, do not touch it while driving, and stop/export only after parking. A passenger may operate manual controls; the driver must not.

The estimator receives the causal runtime stream. During blackout, runtime latitude, longitude, altitude, speed, bearing, provider, accuracy, and freshness are absent. `gnss_raw.csv` may retain physical callbacks solely for offline evaluation. Same-phone GPS is a **phone-GNSS evaluation reference/proxy**, not survey-grade or absolute truth.

## Exact on-phone procedure

1. Install the Phase 11 debug APK and grant precise location/notification access.
2. Outdoors under open sky, securely mount the phone and select the mount metadata while parked.
3. Tap **START LIVE**. Confirm physical GNSS is `FRESH`, runtime GNSS is `AVAILABLE`, callbacks increase, and satellites/TTFF are plausible.
4. Drive normally until **ALIGNMENT READY**. A straight segment above 10 km/h for several seconds is useful; avoid unusual manoeuvres.
5. While still parked before the run, select SHORT (10 s), MEDIUM (30 s), LONG (60 s), or EXTENDED (120 s), then start the automatic field test.
6. The app automatically performs 30 s warm-up, waits for fresh GNSS plus alignment if needed, records a 20 s baseline, masks runtime GNSS for the preset duration, and observes 30 s recovery.
7. Do not touch the phone while driving. The screen must progress through baseline, blackout/IDR, verification/reconciliation, and completion.
8. Park safely, tap **STOP**, open Diagnostics, and export the last local session ZIP.
9. Extract the ZIP to an external private directory such as `C:\IDR-Phone-Tests\session_name`; do not copy it into this Git repository.
10. Run the desktop validator below.

Suggested normal-driving runs are a clear straight segment, a route containing ordinary turns, and a stop-go route. Movement is required for vehicle-direction alignment and road validation; reckless driving or special manoeuvres are not.

## Desktop validation

```powershell
.venv\Scripts\python.exe tools\validate_phase11_android_session.py "C:\IDR-Phone-Tests\session_name"
```

To use an independently logged CSV or GPX reference:

```powershell
.venv\Scripts\python.exe tools\validate_phase11_android_session.py "C:\IDR-Phone-Tests\session_name" --reference "C:\IDR-Phone-Tests\reference.csv" --output "C:\IDR-Phone-Tests\session_name_report"
```

CSV reference columns are `elapsed_seconds`, `latitude_deg`, and `longitude_deg`; optional `accuracy_m`, `speed_mps`, and `callback_status` improve quality gating. GPX track points require UTC timestamps and are treated as elapsed time from the first point. Synchronization quality remains the operator's responsibility.

The validator checks Phase 9/10 schemas and exact runtime/estimator sequence alignment. Reference points are rejected for non-finite/invalid coordinates, non-increasing timestamps, `INVALID` callbacks, horizontal accuracy worse than 50 m when supplied, or speed outside 0-80 m/s when supplied. Missing accuracy is retained and never invented. Reference latitude/longitude is linearly interpolated onto estimator timestamps only in the offline evaluator; this non-causal interpolation is forbidden in runtime code.

Each blackout reports duration, estimated and reference distance, final/mean/RMSE/P95/maximum position error, drift percentage, maximum estimator step, uncertainty start/end, error/sigma relationship, ML state fractions, OOD/correction statistics, localization/alignment states, recovery duration, maximum recovery correction, and post-recovery error. Outputs are JSON, CSV, Markdown, a quality audit, and two plots per blackout. Reports default beside the external session.

The previous `20260901_183640_vivo_V2513_session_2` recording is correctly classified **not evaluable**: it contains no `idr_output.csv` and zero usable physical GNSS reference points. It is plumbing evidence only, not road-accuracy evidence.

## Results to return

Send back `phase11_validation.json`, `PHASE11_FIELD_REPORT.md`, the device/model and mount, route type, whether an independent reference was used, retained/rejected reference counts, blackout duration/distance, final error, RMSE, P95, drift, recovery time/max correction, uncertainty start/end and error/sigma ratio, ML state fractions/OOD statistics, engine average/P95, sensor rates, battery/thermal start/end, and any unexpected UI/state transition. Keep raw private location files private unless deliberately shared.
