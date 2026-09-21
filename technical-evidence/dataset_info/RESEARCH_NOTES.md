# Research Notes

## Evidence hierarchy

For IO-VNBD interpretations, use this order:

1. Actual CSV header and paired numeric behavior
2. Bundled `README_1.pdf` tables and experiment description
3. Bundled `README.md`
4. Explicitly labelled inference when the sources remain incomplete

Never convert an inference into an unqualified fact.

## IO-VNBD collection facts

- The paper describes a Racelogic VBOX Video HD2/CAN logger and GPS antenna at 10 Hz for vehicle data.
- Smartphone data were collected with AndroSensor using a Huawei P20 Pro for the S1 family. The paper states phone sensors at 10 Hz and smartphone GPS at 1 Hz.
- Smartphone sensors include three-axis accelerometer, gyroscope, magnetometer, gravity, azimuth/pitch/roll, GNSS position, speed, accuracy, orientation, and satellite status.
- The collection figure shows positive phone X aligned with vehicle travel direction. Real product operation cannot assume this mount.
- Prefix `S-` means smartphone; `V-` means vehicle/CAN/VBOX.
- Synchronized pairs were manually synchronized by the dataset authors.

## S1 measured timing

- Both streams contain 51,746 rows.
- Phone elapsed time: 0 to 5,174.499 s.
- Vehicle elapsed time: 0 to 5,174.500 s.
- Both have a 0.100 s median interval and approximately 10 Hz rate.
- Phone intervals range from 0.089 to 0.111 s; VBOX intervals range from 0.099 to 0.101 s.
- No timestamp NaNs, duplicates, reversals, or intervals over 0.150 s were found.
- Row-wise phone-minus-VBOX elapsed-clock residual is -1 ms median, 1 ms 95th-percentile absolute, and 10 ms maximum absolute.
- Smartphone local timestamps run from `2019-09-08 10:07:49.546` to `2019-09-08 11:34:04.045`; timezone is not stated.
- VBOX seconds-since-day run from 32,869.0 to 38,043.5. Their apparent one-hour difference from the smartphone wall clock is consistent with a local/UTC offset, but the bundle does not explicitly confirm this, so alignment uses independent elapsed clocks.

## Source discrepancies and resolutions

### Git LFS payload absence

The source ZIP is not a usable sensor dataset by itself. `.gitattributes` marks CSV, ZIP, and JPG files for Git LFS, and the extracted files contain only pointer metadata. The selected pair was fetched separately and verified by the pointer SHA-256 values. No original source file was replaced.

### Gyroscope table typo

PDF Table 4 lists both rows 17 and 18 as “Gyroscope (Pitch).” The real CSV has `GYROSCOPE X`, `GYROSCOPE Y`, and `GYROSCOPE Z`, each in rad/s. Code follows the unambiguous CSV schema.

### Smartphone speed unit

Both PDF and CSV label smartphone GPS speed as Kmh, but the first synchronized row is phone `5.57` versus VBOX `19.969 km/h`; `5.57 m/s = 20.052 km/h`. Across the journey, multiplying phone values by 3.6 makes the traces coherent. The loader therefore:

- preserves `gps_speed_source`
- interprets it as `gps_speed_mps`
- derives `gps_speed_kmh = gps_speed_source * 3.6`

This is a measured correction, not silent relabelling.

### Vehicle height unit

VBOX height is labelled km, but S1 values range from 92.05 to 143.89 while phone altitude ranges from 142.87 to 191.35 m. A road vehicle cannot be at 92-144 km altitude. The loader preserves `height_source` and exposes the same values as `height_m`.

### Smartphone GNSS update cadence

The paper states 1 Hz phone GPS. In S1, latitude/longitude/speed are held and change at a 9.0-second median cadence (534 distinct change rows). The satellite-status text changes at a 1.0-second median cadence. This may reflect logging/export behavior rather than the receiver's internal solution rate. Future blackout evaluation should prefer the 10 Hz VBOX GPS trajectory as the hidden reference while ensuring VBOX/CAN data are never passed to the phone-only estimator.

### Row count

The paper reports 51,790 S1 data points. The hydrated synchronized S and V files each contain 51,746 data rows. The analysis uses actual rows and records the -44 discrepancy.

### Coordinate system

The bundle labels latitude/longitude in degrees and the values match the documented Coventry-area route. It does not explicitly state WGS84 or an EPSG code. Code and plots therefore avoid an unqualified EPSG claim.

## Reference use and limitations

- VBOX GPS and vehicle signals can support evaluation and labels, but final runtime localization must remain phone-only.
- Phone GPS is not independent ground truth; it is a noisy measurement and is sparsely changed in this synchronized export.
- The cumulative VBOX GPS path is 38.044 km, close to the paper's 38.16 km. The phone track is 37.162 km because its coordinates are held for long intervals and are less detailed.
- The current plots establish plausibility and synchronization only. They do not measure dead-reckoning accuracy.
- No local IO-VNBD `LICENSE` file was found. Dataset usage/publication must verify upstream licensing before redistribution.
