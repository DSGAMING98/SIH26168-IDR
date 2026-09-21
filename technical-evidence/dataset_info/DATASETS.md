# Dataset Inventory

Dataset source directories are treated as read-only. ZIP archives have been preserved. Sizes below are approximate extracted sizes measured locally on 2026-08-31.

| Dataset | Local folder | Approx. extracted size | Extracted / completeness | Modalities discovered locally or in bundled docs | Documentation discovered | Intended role | Current status |
|---|---|---:|---|---|---|---|---|
| IO-VNBD | `IO-VNBD-master/` | 1.13 MiB source stubs; 20.0 MiB selected cache | Folder extracted, but all 564 CSVs and 2 inner ZIPs are Git LFS pointers. S1 pair alone is hydrated and checksum-verified in `data/cache/io_vnbd/S1/`. | Smartphone GPS, accelerometer, gravity, gyroscope, magnetometer, orientation; vehicle VBOX GPS and CAN/odometry reference | `README.md`, `README_1.pdf`, `.gitattributes` | Primary development and blackout-evaluation dataset | Milestone 1 complete for S1 only |
| PPC Dataset | `PPC-Dataset-main/` | 0.01 MiB | Repository/docs extracted; advertised 155 MB run payload is not present locally | Triple-frequency multi-GNSS 5 Hz, 100 Hz ADIS16505-2 IMU, reference-station GNSS, position/attitude ground truth | Root, Nagoya, and Tokyo READMEs; MIT `LICENSE` | Later independent vehicle GNSS/IMU validation | Inventory only; payload missing |
| Smartphone Decimeter 2022 | `smartphone-decimeter-2022/` | 21,841.88 MiB (21.33 GiB) | Large train/test tree extracted | Raw smartphone multi-GNSS measurements, uncalibrated accelerometer/gyro/magnetometer in `device_imu.csv`, GNSS logs/NMEA/RINEX, device ground truth for train | Local metadata JSON/CSV; no root README found | Later unseen-phone/unseen-route validation | Inventory only |
| WHU-Smartphone | `WHU-Smartphone-Dataset-main/` | 2,348.38 MiB (2.29 GiB) | Data tree extracted | Raw multifrequency smartphone GNSS from four phones, low-cost GNSS module, base-station data, high-precision GNSS/IMU reference and ground-truth files | Root README plus base-station, conversion-tool, and ground-truth notes | Later GNSS robustness/cross-dataset evaluation; not a primary phone-IMU source | Inventory only |
| MoRPI | `MoRPI-main/` | 46.02 MiB | 143 CSV trajectories extracted | 100 Hz smartphone inertial data from Galaxy S8/S6 on an RC vehicle; indoor/outdoor trajectories | `README.md`, figures | Later pure-inertial method comparison; domain differs from road vehicle | Inventory only |
| GREAT Dataset | `GREAT-Dataset-master/` | 41.41 MiB | Repository/tools/figures extracted; advertised sequence downloads are not present | Vehicle multi-frequency GNSS, tactical 200 Hz IMU, MEMS 100 Hz IMU, cameras, LiDAR, hardware synchronization, smoothed GNSS/IMU reference | `Readme.md`, `CHANGELOG.md`, tools, figures; README states MIT terms | Later high-grade reference comparison, not phone-only validation | Inventory only; sequence payload missing |

Top-level archives are also present: `IO-VNBD-master.zip`, `PPC-Dataset-main.zip`, `smartphone-decimeter-2022.zip`, `WHU-Smartphone-Dataset-main.zip`, `MoRPI-main.zip`, and `GREAT-Dataset-master.zip`.

## IO-VNBD structure

The upstream folder name contains a typo and is preserved exactly:

```text
IO-VNBD-master/
|-- README.md
|-- README_1.pdf
|-- .gitattributes
|-- Synchronised V abd S datasets/
|   |-- Categorised IOVNB Dataset/
|   |   |-- S (Driver A)/, M (Driver B)/, Y (Driver D)/
|   |   `-- Vta/, Vtb/, Vf/, Vw/ (Driver E)
|   `-- Uncategorised IOVNB Dataset/
|       |-- S-Dataset/   (72 smartphone CSV entries)
|       `-- V-Dataset/   (72 paired vehicle CSV entries)
`-- Unsynchronised V and S Dataset/
    |-- Categorised IOVNB (V) Dataset/
    `-- Uncategorised IOVNB (V and S) Dataset/
        |-- S-Dataset/   (97 smartphone CSV entries)
        `-- V-Dataset/   (90 vehicle CSV entries)
```

The synchronized section contains 288 CSV entries total because the same 72 smartphone/vehicle pairs are represented in both categorized and uncategorized layouts. The unsynchronized section contains 276 CSV entries and separately organized route images. Every CSV/JPG/ZIP tracked by the repository is a small LFS pointer in the local source archive.

`S-` denotes smartphone recordings. `V-` denotes vehicle recordings from a Racelogic VBOX HD2 and vehicle CAN bus. The paper says synchronized pairs were collected simultaneously and manually synchronized; not every independent S or V session has a counterpart.

## Smartphone schema

The selected S1 smartphone file has 24 source columns. Whitespace and mixed-encoding unit glyphs are normalized by the loader, while raw headers remain in `session_summary.json`.

| Normalized field | Interpreted unit | Source/documentation note |
|---|---|---|
| `gps_latitude_deg`, `gps_longitude_deg` | degrees | Datum/EPSG not explicitly stated |
| `gps_altitude_m` | m | Matches paper/header |
| `gps_speed_source` | source value | Label says Kmh, values behave as m/s |
| `gps_speed_mps` | m/s | Preserved numeric interpretation |
| `gps_speed_kmh` | km/h | Derived as source x 3.6 |
| `gps_accuracy_m` | m | Matches paper/header |
| `gps_orientation_deg` | degrees | GNSS course/orientation |
| `gps_satellites_in_range` | `used / in-range` text | Example `27 / 28` |
| `time_since_start_ms` | ms | Monotonic logger clock |
| `timestamp_local` | local datetime | Timezone is not supplied |
| `accelerometer_[xyz]_mps2` | m/s^2 | Raw phone axes; includes gravity |
| `gravity_[xyz]_mps2` | m/s^2 | Android gravity estimate |
| `gyroscope_[xyz]_radps` | rad/s | Actual CSV resolves PDF typo |
| `magnetic_field_[xyz]_ut` | microtesla | Present for S1 |
| `orientation_azimuth_deg` | degrees | Android orientation |
| `orientation_pitch_deg` | degrees | Android orientation |
| `orientation_roll_deg` | degrees | Android orientation |

The paper's collection setup aligns positive phone X with vehicle travel direction. This is a property of the documented mounting setup, not a safe runtime assumption for an arbitrary user's phone.

## Vehicle/reference schema

The paired V1 file contains 29 fields at approximately 10 Hz. Key fields for research and evaluation are GPS satellites, seconds since start of day, latitude/longitude, GPS velocity, heading, height, vertical velocity, sample period, steering angle, four wheel speeds, yaw rate, indicated speed, longitudinal/lateral acceleration, and vehicle control/state values.

Units are documented in the bundled paper and CSV header. Two cautions apply:

- `Height (km)` is numerically metre-scale (92.05-143.89 for S1) and is exposed as `height_m` while preserving `height_source`.
- The VBOX GPS trajectory is a useful synchronized reference, but the bundle does not establish it as survey-grade ground truth. Reports must call it a reference, not fabricate a higher accuracy class.

## Selected first journey: S1

Files used:

- Smartphone: `data/cache/io_vnbd/S1/S-S1.csv`
- Vehicle reference: `data/cache/io_vnbd/S1/V-S1.csv`

Upstream LFS checksums:

- `S-S1.csv`: `8c4d2678fd79cce7c819437a7d85d7d5cb9e47a63dac7d171ead3f9d052deff1`, 10,011,984 bytes
- `V-S1.csv`: `29e92ed9bcb2d711e651246675c435b3f9499c040cfcad367624e8720c0dc891`, 10,967,129 bytes

Why selected:

- 86.3 minutes and 38.16 km in the paper, long enough for many future 10/30/60/120-second blackout windows
- Synchronized smartphone and VBOX streams
- Nine roundabouts, five reverse manoeuvres, a hilly B-road, ring road, and hard braking
- Full smartphone accelerometer, gravity, gyro, magnetometer, GNSS, and orientation fields
- Exact equal row count after hydration

Measured session details are in `results/io_vnbd/s1/session_summary.json`.

## Phase 2 field policy

The blackout harness uses the synchronized smartphone `elapsed_s` clock and treats each requested interval as half-open: `start_s <= elapsed_s < start_s + duration_s`.

Runtime sensor data always includes elapsed/logger time, local timestamp, accelerometer, gravity, gyroscope, magnetic field, and Android phone-orientation azimuth/pitch/roll, plus `gnss_available`. GPS latitude, longitude, altitude, source and normalized speed, accuracy, GPS orientation/course, and satellite status are excluded from the aligned runtime sensor table. A separate runtime GNSS-observation table contains those GNSS measurements only at available times; blackout rows do not exist in that table.

The VBOX stream, including its position, velocity, heading, CAN, and vehicle-motion fields, is kept in a separate `EvaluationReference`. It is used to select/describe scenarios, calculate blackout reference distance, validate alignment, and plot evidence. It is not a runtime estimator input.

This policy relies on the bundled schema's explicit distinction between GPS orientation and the Android phone orientation fields. It does not assume an unstated coordinate datum, sensor fusion implementation, or phone-to-vehicle mounting transform.

## Phase 3 orientation uncertainty

The paper's sensor-axis figure states that mounted phone +X was intended to follow vehicle travel. S1 gravity is numerically almost entirely device +Z (mean approximately `[-0.0002, 0.0000, 9.8065] m/s²`). However, interpreting the exported azimuth/pitch/roll with the standard Android Euler convention produces a median gravity tilt of approximately 97 degrees from local Up. This is a measured inconsistency between the gravity vector and that interpretation, not evidence that either individual field is corrupt. The raw baseline freezes the documented Android convention without reference-based sign/order selection; resolving possible app remapping, mounting, or export semantics is a Phase 4 task.

## Phase 4 orientation findings

The bundled paper identifies AndroSensor as the recorder, depicts mounted phone +X along vehicle travel, and says per-axis gravity is provided for acceleration correction. It does not specify whether AndroSensor remapped the exported orientation or gyroscope axes. Official Android `SensorManager` conventions therefore do not by themselves explain S1.

Across every Phase 4 benchmark, measured gravity magnitude is approximately 9.8066 m/s² and gravity direction is within 0.18 degrees of device +Z, while the frozen Phase 3 Euler interpretation implies about 95-99 degrees tilt. Runtime-safe pre-blackout comparisons also show that integrated exported gyroscope Y, with negative sign, follows phone-GNSS course changes much more closely than the gravity-aligned Z channel. For example, the 30-, 60-, and 120-second calibration windows produce Y/course correlations of approximately -0.998, -1.000, and -0.997 with fitted scales near -0.90 to -0.95. These observations establish an S1/AndroSensor export remapping; they do not prove a universal Android convention.

Phase 4 consequently uses measured gravity and documented +X to form forward/left/up, treats exported pitch/roll as diagnostics only, fixes the S1 yaw-rate channel to `-gyroscope_y`, and calibrates exported azimuth against strictly pre-blackout phone-GNSS course. Arbitrary future phone mounts still require their own runtime calibration.
