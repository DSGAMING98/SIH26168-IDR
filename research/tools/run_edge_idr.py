"""Run the generic NavGhost external-IMU edge engine on a CSV stream."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from idr.edge import (  # noqa: E402
    EdgeIdrConfig,
    EdgeIdrEngine,
    ExternalImuSample,
    RoadSegment,
    StreamingRoadMatcher,
)


INPUT_COLUMNS = (
    "timestamp_s",
    "accel_x_mps2",
    "accel_y_mps2",
    "accel_z_mps2",
    "gyro_x_radps",
    "gyro_y_radps",
    "gyro_z_radps",
)


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run NavGhost on a native-rate external IMU CSV")
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("output_csv", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--road-segments", type=Path, help="Optional local-ENU JSON array of road segments")
    return parser.parse_args()


def load_road_matcher(path: Path | None) -> StreamingRoadMatcher | None:
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    segments = [
        RoadSegment(
            float(item["start_east_m"]),
            float(item["start_north_m"]),
            float(item["end_east_m"]),
            float(item["end_north_m"]),
        )
        for item in payload
    ]
    return StreamingRoadMatcher(segments)


def run(input_path: Path, output_path: Path, road_path: Path | None) -> dict[str, object]:
    matcher = load_road_matcher(road_path)
    engine = EdgeIdrEngine(EdgeIdrConfig(), road_matcher=matcher)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with input_path.open("r", encoding="utf-8-sig", newline="") as source, output_path.open(
        "w", encoding="utf-8", newline=""
    ) as destination:
        reader = csv.DictReader(source)
        missing = set(INPUT_COLUMNS).difference(reader.fieldnames or ())
        if missing:
            raise ValueError(f"External IMU CSV is missing columns: {sorted(missing)}")
        writer = csv.DictWriter(
            destination,
            fieldnames=(
                "timestamp_s", "east_m", "north_m", "speed_mps", "yaw_rad",
                "acceleration_bias_mps2", "gyro_bias_radps", "stationary",
                "update_rate_hz", "ml_updates", "map_updates",
            ),
        )
        writer.writeheader()
        for row in reader:
            state = engine.ingest_imu(
                ExternalImuSample(
                    timestamp_s=float(row["timestamp_s"]),
                    acceleration_mps2=tuple(float(row[f"accel_{axis}_mps2"]) for axis in "xyz"),
                    angular_rate_radps=tuple(float(row[f"gyro_{axis}_radps"]) for axis in "xyz"),
                    stationary_hint=row.get("stationary_hint", "").strip().lower() in {"1", "true", "yes"},
                )
            )
            writer.writerow({name: getattr(state, name) for name in writer.fieldnames})
    processing_s = time.perf_counter() - started
    state = engine.state()
    return {
        "schema_version": 1,
        "input": str(input_path.resolve()),
        "output": str(output_path.resolve()),
        "samples": state.samples_processed,
        "observed_input_rate_hz": state.update_rate_hz,
        "processing_seconds": processing_s,
        "processing_samples_per_second": state.samples_processed / processing_s if processing_s > 0 else None,
        "native_rate_propagation": True,
        "non_holonomic_constraint": True,
        "road_matching_enabled": matcher is not None,
        "ml_correction_interface": True,
        "note": "Throughput is host software evidence, not a physical FOG accuracy result.",
    }


def main() -> None:
    args = arguments()
    summary = run(args.input_csv, args.output_csv, args.road_segments)
    summary_path = args.summary or args.output_csv.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
