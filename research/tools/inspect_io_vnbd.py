#!/usr/bin/env python3
"""Inspect one synchronized IO-VNBD journey and create Milestone 1 outputs."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / ".deps"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from idr.io_vnbd import (  # noqa: E402
    cumulative_track_distance_m,
    held_measurement_update_statistics,
    load_journey,
    sampling_statistics,
    schema_units,
    sha256_file,
    synchronization_statistics,
)


COLORS = {
    "x": "#0072B2",
    "y": "#D55E00",
    "z": "#009E73",
    "phone": "#CC79A7",
    "vehicle": "#0072B2",
    "grid": "#D9DEE5",
}


def _style_axis(axis: Any) -> None:
    axis.grid(True, color=COLORS["grid"], linewidth=0.6, alpha=0.8)
    axis.spines[["top", "right"]].set_visible(False)


def _save_figure(figure: Any, path: Path) -> None:
    figure.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def plot_trajectory(journey: Any, output: Path) -> None:
    phone = journey.smartphone
    vehicle = journey.vehicle
    position_change = held_measurement_update_statistics(phone)
    median_change_s = position_change["median_interval_s"]
    figure, axis = plt.subplots(figsize=(9.5, 8.0))
    axis.plot(
        vehicle["longitude_deg"],
        vehicle["latitude_deg"],
        color=COLORS["vehicle"],
        linewidth=1.2,
        label="Vehicle GPS reference (10 Hz)",
        zorder=2,
    )
    axis.plot(
        phone["gps_longitude_deg"],
        phone["gps_latitude_deg"],
        color=COLORS["phone"],
        linewidth=0.8,
        alpha=0.75,
        label=f"Smartphone GPS (median {median_change_s:.1f} s between value changes)",
        zorder=3,
    )
    axis.scatter(vehicle["longitude_deg"].iloc[0], vehicle["latitude_deg"].iloc[0], s=55, marker="o", color="#009E73", label="Start", zorder=4)
    axis.scatter(vehicle["longitude_deg"].iloc[-1], vehicle["latitude_deg"].iloc[-1], s=65, marker="X", color="#E69F00", label="End", zorder=4)
    axis.set_title(f"IO-VNBD {journey.session_id}: full synchronized GNSS trajectory", loc="left", weight="bold")
    axis.set_xlabel("Longitude (degrees; GPS datum not stated in bundled documentation)")
    axis.set_ylabel("Latitude (degrees; GPS datum not stated in bundled documentation)")
    axis.set_aspect("equal", adjustable="datalim")
    axis.legend(frameon=False, loc="best")
    _style_axis(axis)
    _save_figure(figure, output)


def plot_axes(journey: Any, output: Path, prefix: str, title: str, ylabel: str) -> None:
    phone = journey.smartphone
    time_min = phone["elapsed_s"] / 60.0
    figure, axes = plt.subplots(3, 1, figsize=(12.5, 8.0), sharex=True)
    for axis, coordinate in zip(axes, ("x", "y", "z"), strict=True):
        column = f"{prefix}_{coordinate}_{'mps2' if prefix == 'accelerometer' else 'radps'}"
        axis.plot(time_min, phone[column], color=COLORS[coordinate], linewidth=0.55)
        axis.set_ylabel(f"{coordinate.upper()} ({ylabel})")
        _style_axis(axis)
    axes[0].set_title(f"IO-VNBD {journey.session_id}: {title}", loc="left", weight="bold")
    axes[-1].set_xlabel("Elapsed time (minutes)")
    figure.tight_layout()
    _save_figure(figure, output)


def plot_speed(journey: Any, output: Path) -> None:
    phone = journey.smartphone
    vehicle = journey.vehicle
    figure, axis = plt.subplots(figsize=(12.5, 5.0))
    axis.plot(vehicle["elapsed_s"] / 60.0, vehicle["velocity_kmh"], color=COLORS["vehicle"], linewidth=0.8, label="Vehicle GPS velocity")
    axis.plot(phone["elapsed_s"] / 60.0, phone["gps_speed_kmh"], color=COLORS["phone"], linewidth=0.8, alpha=0.8, label="Smartphone GPS speed")
    axis.set_title(f"IO-VNBD {journey.session_id}: reference speed", loc="left", weight="bold")
    axis.set_xlabel("Elapsed time (minutes)")
    axis.set_ylabel("Speed (km/h)")
    axis.legend(frameon=False, ncol=2)
    _style_axis(axis)
    _save_figure(figure, output)


def plot_heading(journey: Any, output: Path) -> None:
    phone = journey.smartphone
    vehicle = journey.vehicle
    figure, axes = plt.subplots(2, 1, figsize=(12.5, 7.0), sharex=True)
    axes[0].plot(vehicle["elapsed_s"] / 60.0, vehicle["heading_deg"], color=COLORS["vehicle"], linewidth=0.65, label="Vehicle GPS heading")
    axes[0].plot(phone["elapsed_s"] / 60.0, phone["gps_orientation_deg"], color=COLORS["phone"], linewidth=0.65, alpha=0.75, label="Smartphone GPS orientation")
    axes[0].set_ylabel("Course/heading (degrees)")
    axes[0].legend(frameon=False, ncol=2)
    axes[1].plot(phone["elapsed_s"] / 60.0, phone["orientation_azimuth_deg"], color="#7A5195", linewidth=0.55, label="Azimuth")
    axes[1].plot(phone["elapsed_s"] / 60.0, phone["orientation_pitch_deg"], color="#EF5675", linewidth=0.55, alpha=0.85, label="Pitch")
    axes[1].plot(phone["elapsed_s"] / 60.0, phone["orientation_roll_deg"], color="#FFA600", linewidth=0.55, alpha=0.85, label="Roll")
    axes[1].set_ylabel("Phone orientation (degrees)")
    axes[1].set_xlabel("Elapsed time (minutes)")
    axes[1].legend(frameon=False, ncol=3)
    axes[0].set_title(f"IO-VNBD {journey.session_id}: heading and phone orientation", loc="left", weight="bold")
    for axis in axes:
        _style_axis(axis)
    figure.tight_layout()
    _save_figure(figure, output)


def _finite_range(values: Any) -> dict[str, float | None]:
    array = np.asarray(values, dtype=float)
    finite = array[np.isfinite(array)]
    if not finite.size:
        return {"min": None, "max": None}
    return {"min": float(finite.min()), "max": float(finite.max())}


def build_summary(journey: Any, output_files: list[Path]) -> dict[str, Any]:
    root = ROOT.resolve()
    phone = journey.smartphone
    vehicle = journey.vehicle
    summary = {
        "dataset": "IO-VNBD",
        "session_id": journey.session_id,
        "selection": {
            "documented_vehicle_session": "V-S1",
            "documented_smartphone_session": "S-S1",
            "documented_scenarios": [
                "B-road B4101",
                "9 roundabouts",
                "5 reverse manoeuvres",
                "hilly road",
                "A4053 ring road",
                "hard braking",
            ],
            "documented_duration_min": 86.3,
            "documented_distance_km": 38.16,
            "documented_row_count": 51790,
            "reason": "Long synchronized smartphone/reference journey with varied turns and more than enough duration for later 10/30/60/120 s blackout windows.",
        },
        "source_files": {
            "smartphone": str(journey.smartphone_path.resolve().relative_to(root)).replace("\\", "/"),
            "vehicle_reference": str(journey.vehicle_path.resolve().relative_to(root)).replace("\\", "/"),
            "smartphone_sha256": sha256_file(journey.smartphone_path),
            "vehicle_sha256": sha256_file(journey.vehicle_path),
            "upstream_tree_status": "All original local IO-VNBD CSV and ZIP entries are Git LFS pointer stubs; selected payloads are checksum-verified cache files.",
        },
        "rows": {
            "smartphone": int(len(phone)),
            "vehicle_reference": int(len(vehicle)),
            "difference_from_documented_count": int(len(phone) - 51790),
        },
        "sampling": {
            "smartphone_imu": sampling_statistics(phone["elapsed_s"]),
            "vehicle_reference": sampling_statistics(vehicle["elapsed_s"]),
            "smartphone_gnss_solution_value_changes": {
                **held_measurement_update_statistics(phone),
                "interpretation": "Observed changes in held latitude/longitude/speed values; this is not proof of the receiver's internal update rate.",
                "documentation_comparison": "Bundled paper states 1 Hz smartphone GPS updates, while S1 solution values change at a 9 s median cadence.",
            },
        },
        "synchronization": synchronization_statistics(journey),
        "time": {
            "smartphone_local_start": phone["timestamp_local"].iloc[0].isoformat(),
            "smartphone_local_end": phone["timestamp_local"].iloc[-1].isoformat(),
            "smartphone_local_timezone": "not supplied by dataset",
            "vehicle_start_seconds_since_day": float(vehicle["time_since_start_of_day_s"].iloc[0]),
            "vehicle_end_seconds_since_day": float(vehicle["time_since_start_of_day_s"].iloc[-1]),
        },
        "trajectory": {
            "coordinate_system": "GPS latitude/longitude in degrees; the bundled paper does not state a datum or EPSG code. Values are consistent with the documented UK route.",
            "smartphone_latitude_deg": _finite_range(phone["gps_latitude_deg"]),
            "smartphone_longitude_deg": _finite_range(phone["gps_longitude_deg"]),
            "vehicle_latitude_deg": _finite_range(vehicle["latitude_deg"]),
            "vehicle_longitude_deg": _finite_range(vehicle["longitude_deg"]),
            "smartphone_track_distance_km": cumulative_track_distance_m(phone["gps_latitude_deg"], phone["gps_longitude_deg"]) / 1000.0,
            "vehicle_track_distance_km": cumulative_track_distance_m(vehicle["latitude_deg"], vehicle["longitude_deg"]) / 1000.0,
        },
        "value_ranges": {
            "smartphone_gps_speed_source_labelled_kmh": _finite_range(phone["gps_speed_source"]),
            "smartphone_gps_speed_interpreted_mps": _finite_range(phone["gps_speed_mps"]),
            "smartphone_gps_speed_kmh": _finite_range(phone["gps_speed_kmh"]),
            "vehicle_velocity_kmh": _finite_range(vehicle["velocity_kmh"]),
            "smartphone_gps_accuracy_m": _finite_range(phone["gps_accuracy_m"]),
            "vehicle_height_source_labelled_km_but_interpreted_m": _finite_range(vehicle["height_source"]),
            "smartphone_gps_altitude_m": _finite_range(phone["gps_altitude_m"]),
        },
        "unit_findings": {
            "smartphone_gps_speed": {
                "source_label": "Kmh",
                "interpreted_unit": "m/s",
                "action": "Preserve gps_speed_source, expose gps_speed_mps, and derive gps_speed_kmh by multiplying by 3.6.",
                "evidence": "First paired row is 5.57 in the phone file versus 19.969 km/h in VBOX; 5.57 m/s equals 20.052 km/h.",
            },
            "vehicle_height": {
                "source_label": "km",
                "interpreted_unit": "m",
                "action": "Preserve height_source and expose height_m without scaling.",
                "evidence": "S1 source values span roughly 92-144 while simultaneous phone altitude spans roughly 143-191 m; 92-144 km is impossible for a road vehicle.",
            },
        },
        "missing_values": {
            "smartphone_total": int(phone.isna().sum().sum()),
            "vehicle_reference_total": int(vehicle.isna().sum().sum()),
            "smartphone_unparsed_datetime_count": int(phone["timestamp_local"].isna().sum()),
        },
        "schema": {
            "smartphone_units": schema_units("smartphone"),
            "vehicle_reference_units": schema_units("vehicle"),
            "smartphone_raw_headers": list(journey.smartphone_raw_headers),
            "vehicle_raw_headers": list(journey.vehicle_raw_headers),
        },
        "generated_outputs": [str(path.resolve().relative_to(root)).replace("\\", "/") for path in output_files],
    }
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", default="S1", help="Synchronized session id (default: S1)")
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results" / "io_vnbd" / "s1")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    journey = load_journey(args.session, args.project_root)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    files = [
        output / "s1_gnss_trajectory.png",
        output / "s1_accelerometer.png",
        output / "s1_gyroscope.png",
        output / "s1_speed.png",
        output / "s1_heading_orientation.png",
    ]
    plot_trajectory(journey, files[0])
    plot_axes(journey, files[1], "accelerometer", "smartphone accelerometer", "m/s²")
    plot_axes(journey, files[2], "gyroscope", "smartphone gyroscope", "rad/s")
    plot_speed(journey, files[3])
    plot_heading(journey, files[4])
    summary_path = output / "session_summary.json"
    summary = build_summary(journey, files + [summary_path])
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "session": journey.session_id,
        "smartphone_rows": len(journey.smartphone),
        "vehicle_rows": len(journey.vehicle),
        "duration_s": summary["sampling"]["smartphone_imu"]["duration_s"],
        "smartphone_hz": summary["sampling"]["smartphone_imu"]["approx_frequency_hz"],
        "vehicle_hz": summary["sampling"]["vehicle_reference"]["approx_frequency_hz"],
        "output": str(output),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
