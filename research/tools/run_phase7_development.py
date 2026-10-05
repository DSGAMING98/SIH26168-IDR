#!/usr/bin/env python3
"""Compare the small Phase 7 profile set on development-only S1 intervals."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from idr.blackout import BlackoutWindow, create_blackout_experiment  # noqa: E402
from idr.calibrated_dr import Phase4Settings  # noqa: E402
from idr.hybrid.hybrid_idr import HybridSettings  # noqa: E402
from idr.io_vnbd import load_journey  # noqa: E402
from idr.map_matching import MapMatcherConfig, RoadGraph  # noqa: E402
from idr.ml.velocity_model import load_velocity_bundle  # noqa: E402
from idr.phase7 import Phase7Config, evaluate_phase7_runtime, run_phase7_runtime  # noqa: E402


def load_json(path: Path | str) -> dict:
    source = Path(path)
    if not source.is_absolute():
        source = ROOT / source
    return json.loads(source.read_text(encoding="utf-8"))


def main() -> int:
    phase7 = load_json("configs/phase7/io_vnbd_s1_phase7.json")
    development = load_json(phase7["development_config"])
    phase6 = load_json(phase7["phase6_config"])
    phase5 = load_json(phase7["phase5_config"])
    phase4_settings = Phase4Settings.from_dict(load_json(phase7["phase4_config"]))
    hybrid_settings = HybridSettings.from_dict(load_json(phase5["ekf_config"]))
    model = load_velocity_bundle(ROOT / phase5["checkpoint_path"])
    map_config = load_json(phase6["map_config"])
    graph = RoadGraph.load(ROOT / map_config["cache_path"])
    matcher = MapMatcherConfig.from_dict(phase6["matcher"])
    journey = load_journey("S1", project_root_path=ROOT)
    base = Phase7Config.from_dict(phase7["settings"])
    rows = []
    for profile_name, overrides in development["profiles"].items():
        settings = replace(base, **overrides)
        settings.validate()
        for item in development["windows"]:
            settings = replace(settings, post_blackout_tail_s=float(item["post_blackout_tail_s"]))
            window = BlackoutWindow(float(item["start_s"]), float(item["duration_s"]))
            experiment = create_blackout_experiment(journey, window)
            run = run_phase7_runtime(
                experiment.runtime, window, phase4_settings, hybrid_settings,
                model, graph, matcher, settings,
            )
            metrics = evaluate_phase7_runtime(run, experiment.reference).metrics
            rows.append({
                "profile": profile_name,
                "window": item["id"],
                "hard_snap_jump_m": metrics["b1_first_fresh_fix_hard_snap_jump_m"],
                "p7_max_step_m": metrics["phase7_maximum_instantaneous_correction_m"],
                "recovery_duration_s": metrics["recovery_duration_s"],
                "time_to_active_s": metrics["time_to_return_gnss_active_s"],
                "post_rmse_m": metrics["post_reacquisition_rmse_m"],
                "fresh_delay_s": metrics["fresh_fix_delay_after_blackout_s"],
                "candidate_rejections": metrics["candidate_reacquisition_fixes_rejected"],
            })
            print(profile_name, item["id"], rows[-1])
    output = ROOT / "results/phase7/io_vnbd/s1/development"
    output.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    frame.to_csv(output / "profile_summary.csv", index=False)
    (output / "profile_summary.json").write_text(
        json.dumps(rows, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
