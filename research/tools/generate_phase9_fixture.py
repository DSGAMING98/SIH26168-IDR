"""Generate the deterministic, entirely synthetic Phase 9 Android fixture."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "tests" / "fixtures" / "phase9_android_session"
ORIGIN_NS = 1_000_000_000_000
START = datetime(2026, 1, 1, tzinfo=timezone.utc)
FIXTURE_FILES = frozenset({"session_metadata.json", "imu_raw.csv", "gnss_raw.csv", "runtime_10hz.csv", "events.jsonl"})


def utc(elapsed: float) -> str:
    return (START + timedelta(seconds=elapsed)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def generate(output: Path) -> None:
    if output.exists():
        if not output.is_dir():
            raise ValueError(f"Fixture output is not a directory: {output}")
        unexpected = {item.name for item in output.iterdir()}.difference(FIXTURE_FILES)
        if unexpected:
            raise ValueError(f"Refusing to replace a directory containing non-fixture files: {sorted(unexpected)}")
        for name in FIXTURE_FILES:
            path = output / name
            if path.is_file():
                path.unlink()
    else:
        output.mkdir(parents=True)
    sensors = ("accelerometer", "gyroscope", "magnetometer", "gravity", "rotation_vector")
    metadata = {
        "schema_version": 2,
        "session_id": "synthetic_phase9_android_session",
        "device_manufacturer": "Synthetic",
        "device_model": "FixturePhone",
        "android_version": "16",
        "android_sdk": 36,
        "app_version": "0.9.0",
        "session_origin_monotonic_ns": ORIGIN_NS,
        "session_start_utc": utc(0.0),
        "session_end_utc": utc(4.0),
        "timestamp_semantics": "Synthetic SensorEvent.timestamp and Location.elapsedRealtimeNanos monotonic nanoseconds.",
        "device_frame": "Android sensor frame: +X right, +Y toward phone top, +Z out of screen; no vehicle-forward claim.",
        "units": {
            "accelerometer": "m/s^2", "gyroscope": "rad/s", "magnetometer": "microtesla",
            "speed": "m/s", "angles": "degrees", "position": "WGS84 latitude/longitude degrees",
        },
        "requested_sampling_period_us": 20_000,
        "normalized_target_hz": 10.0,
        "location_provider": "gps",
        "storage": "synthetic fixture; app-private local files; no upload or analytics",
        "availability": {
            "accelerometer": True, "gyroscope": True, "magnetometer": True,
            "gravity": True, "rotation_vector": True, "gps_provider": True,
        },
        "sensors": [
            {"kind": name, "available": True, "name": f"Synthetic {name}", "vendor": "Fixture", "resolution": 0.001, "maximum_range": 100.0}
            for name in sensors
        ],
        "observed_rates": {
            "accelerometer_hz": 50.0, "gyroscope_hz": 50.0, "magnetometer_hz": 50.0,
            "gravity_hz": 50.0, "rotation_vector_hz": 50.0, "normalized_hz": 10.0,
        },
        "gnss_diagnostics": {
            "physical_callback_count": 5,
            "last_physical_gnss_timestamp_ns": ORIGIN_NS + 3_500_000_000,
            "first_valid_fix_timestamp_ns": ORIGIN_NS,
            "time_to_first_fix_seconds": 0.0,
            "gnss_status_available": True,
            "satellites_visible": 12,
            "satellites_used_in_fix": 6,
        },
        "fixture_notice": "SYNTHETIC ONLY — contains no real location recording",
    }
    (output / "session_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    raw_header = ("logger_sequence_id", "sensor_type", "event_timestamp_ns", "elapsed_seconds", "wall_clock_utc", "x", "y", "z", "w", "accuracy")
    with (output / "imu_raw.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=raw_header)
        writer.writeheader()
        sequence = 0
        for index in range(200):
            elapsed = index / 50.0
            for sensor in sensors:
                phase = elapsed * 0.6
                if sensor == "accelerometer": values = (0.2 * math.sin(phase), 0.1 * math.cos(phase), 9.81, "")
                elif sensor == "gyroscope": values = (0.01, 0.02, 0.03 * math.sin(phase), "")
                elif sensor == "magnetometer": values = (22.0, -4.0, 41.0, "")
                elif sensor == "gravity": values = (0.0, 0.0, 9.81, "")
                else: values = (0.0, 0.0, math.sin(phase / 2.0), math.cos(phase / 2.0))
                writer.writerow(dict(zip(raw_header, (sequence, sensor, ORIGIN_NS + index * 20_000_000, f"{elapsed:.9f}", utc(elapsed), *values, 3))))
                sequence += 1

    gnss_header = (
        "logger_sequence_id", "location_timestamp_ns", "elapsed_seconds", "wall_clock_utc", "latitude_deg", "longitude_deg",
        "altitude_m", "speed_mps", "bearing_deg", "accuracy_m", "vertical_accuracy_m", "speed_accuracy_mps",
        "bearing_accuracy_deg", "provider", "callback_status", "masked_from_runtime",
    )
    fixes = (
        (0.0, 12.9716000, 77.5946000, "FRESH", False),
        (1.0, 12.9716000, 77.5946000, "STALE", False),
        (2.0, 12.9716500, 77.5946500, "FRESH", True),
        (2.5, 12.9716800, 77.5946800, "FRESH", False),
        (3.5, 12.9717200, 77.5947200, "FRESH", False),
    )
    with (output / "gnss_raw.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=gnss_header)
        writer.writeheader()
        for sequence, (elapsed, lat, lon, status, masked) in enumerate(fixes):
            writer.writerow(dict(zip(gnss_header, (sequence, ORIGIN_NS + round(elapsed * 1e9), f"{elapsed:.9f}", utc(elapsed), lat, lon, 900.0, 5.0, 45.0, 3.0, 5.0, 0.2, 2.0, "gps", status, str(masked).lower()))))

    runtime_header = (
        "sequence_id", "elapsed_seconds", "monotonic_timestamp_ns", "wall_clock_utc",
        "accelerometer_x_mps2", "accelerometer_y_mps2", "accelerometer_z_mps2",
        "gyroscope_x_radps", "gyroscope_y_radps", "gyroscope_z_radps",
        "magnetometer_x_ut", "magnetometer_y_ut", "magnetometer_z_ut",
        "gravity_x_mps2", "gravity_y_mps2", "gravity_z_mps2", "rotation_qx", "rotation_qy", "rotation_qz", "rotation_qw",
        "gnss_latitude_deg", "gnss_longitude_deg", "gnss_altitude_m", "gnss_speed_mps", "gnss_bearing_deg",
        "gnss_accuracy_m", "gnss_vertical_accuracy_m", "gnss_speed_accuracy_mps", "gnss_bearing_accuracy_deg", "gnss_provider",
        "gnss_fix_age_seconds", "gnss_is_fresh", "gnss_status", "simulated_blackout",
        "blackout_masks_real_fix", "physical_gnss_callback_count", "latest_physical_callback_age_seconds",
        "last_physical_gnss_timestamp_ns", "first_valid_gnss_fix_timestamp_ns", "time_to_first_fix_seconds",
        "gnss_status_available", "satellites_visible", "satellites_used_in_fix",
        "accelerometer_available", "gyroscope_available", "magnetometer_available", "gravity_available", "rotation_vector_available", "gps_provider_available",
        "ml_ood_state", "ml_feature_exceedance", "ml_correction_accepted",
    )
    with (output / "runtime_10hz.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=runtime_header)
        writer.writeheader()
        for index in range(40):
            elapsed = index / 10.0
            blackout = 1.5 <= elapsed < 2.5
            stale = 1.0 <= elapsed < 1.5
            if elapsed < 1.0: lat, lon, age = 12.9716000, 77.5946000, elapsed
            elif elapsed < 2.5: lat, lon, age = 12.9716000, 77.5946000, elapsed - 1.0
            elif elapsed < 3.5: lat, lon, age = 12.9716800, 77.5946800, elapsed - 2.5
            else: lat, lon, age = 12.9717200, 77.5947200, elapsed - 3.5
            gnss = ("",) * 10 if blackout else (lat, lon, 900.0, 5.0, 45.0, 3.0, 5.0, 0.2, 2.0, "gps")
            status = "SIMULATED_BLACKOUT" if blackout else ("STALE" if stale else "FRESH")
            prior_fixes = [fix for fix in fixes if fix[0] <= elapsed]
            last_fix_elapsed = prior_fixes[-1][0]
            row = (
                index, f"{elapsed:.9f}", ORIGIN_NS + index * 100_000_000, utc(elapsed),
                0.2 * math.sin(elapsed * 0.6), 0.1 * math.cos(elapsed * 0.6), 9.81,
                0.01, 0.02, 0.03 * math.sin(elapsed * 0.6), 22.0, -4.0, 41.0, 0.0, 0.0, 9.81,
                0.0, 0.0, math.sin(elapsed * 0.3), math.cos(elapsed * 0.3), *gnss,
                age, str(not blackout and not stale).lower(), status, str(blackout).lower(),
                str(blackout).lower(), len(prior_fixes), elapsed - last_fix_elapsed,
                ORIGIN_NS + round(last_fix_elapsed * 1e9), ORIGIN_NS, 0.0, "true", 12, 6,
                "true", "true", "true", "true", "true", "true", "NOT_EVALUATED", "", "",
            )
            writer.writerow(dict(zip(runtime_header, row)))

    events = (
        {"wall_clock_utc": utc(0.0), "type": "SESSION_STARTED", "message": "Synthetic fixture"},
        {"wall_clock_utc": utc(0.0), "type": "GNSS_STATUS_AVAILABLE", "message": "GnssStatus.Callback registered"},
        {"wall_clock_utc": utc(0.0), "type": "GNSS_VALID_FIRST_FIX", "message": "time_to_first_fix_seconds=0.0"},
        {"wall_clock_utc": utc(0.0), "type": "GNSS_SATELLITES", "message": "visible=12,used=6"},
        {"wall_clock_utc": utc(1.5), "type": "SIMULATED_BLACKOUT_STARTED", "message": "Runtime GNSS masked"},
        {"wall_clock_utc": utc(2.5), "type": "SIMULATED_BLACKOUT_STOPPED", "message": "Runtime GNSS restored"},
        {"wall_clock_utc": utc(4.0), "type": "SESSION_STOPPED", "message": "Synthetic fixture complete"},
    )
    (output / "events.jsonl").write_text("".join(json.dumps(item) + "\n" for item in events), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    generate(args.output.resolve())
    print(args.output.resolve())


if __name__ == "__main__":
    main()
