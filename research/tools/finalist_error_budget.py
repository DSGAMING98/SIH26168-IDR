"""Offline-only error diagnosis; reference values never enter runtime estimators."""
from pathlib import Path
import json
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from idr.blackout import BlackoutWindow
from idr.io_vnbd import load_journey
from idr.calibrated_dr import Phase4Settings
from idr.hybrid.hybrid_idr import HybridSettings
from idr.ml.velocity_model import load_velocity_bundle
from idr.phase5_pipeline import run_phase5_scenario


def main():
    out = ROOT / 'results/finalist_20261005/error_budget'
    out.mkdir(parents=True, exist_ok=True)
    read = lambda p: json.loads((ROOT / p).read_text())
    journey = load_journey('S1', project_root_path=ROOT)
    p4 = Phase4Settings.from_dict(read('configs/phase4/io_vnbd_s1_classical.json'))
    settings = HybridSettings.from_dict(read('configs/phase5/io_vnbd_s1_ekf.json'))
    bundle = load_velocity_bundle(ROOT / 'models/phase5/io_vnbd_s1/velocity_gru.pt')
    rows = []
    for scenario in read('configs/blackouts/io_vnbd_s1.json')['scenarios']:
        if not scenario.get('standard'):
            continue
        run = run_phase5_scenario(journey, BlackoutWindow(scenario['start_s'], scenario['duration_s']), p4, settings, bundle)
        cal = run.ekf_prediction.calibration
        (out / (scenario['id'] + '_calibration.json')).write_text(json.dumps(cal.to_dict(), indent=2))
        for name, ev in [('classical', run.ekf_evaluation), ('hybrid', run.hybrid_evaluation)]:
            t = ev.timeseries
            ref = run.experiment.reference.data.set_index('runtime_elapsed_s').loc[t.elapsed_s]
            yaw = np.deg2rad(t.estimated_yaw_deg.to_numpy())
            refyaw = np.deg2rad(ref.heading_deg.to_numpy())
            dyaw = np.arctan2(np.sin(yaw-refyaw), np.cos(yaw-refyaw))
            speed = t.estimated_speed_mps.to_numpy()
            refspeed = t.reference_speed_mps.to_numpy()
            dt = t.dt_s.to_numpy()
            moving = refspeed > 2
            unit = np.column_stack((np.sin(yaw), np.cos(yaw)))
            refunit = np.column_stack((np.sin(refyaw), np.cos(refyaw)))
            # Diagnostic velocity decomposition, not a runtime or performance result.
            # v*u - vr*ur = (v-vr)*ur + vr*(u-ur) + (v-vr)*(u-ur).
            speed_vec = np.sum(((speed-refspeed)*dt)[:,None]*refunit, axis=0)
            yaw_vec = np.sum((refspeed*dt)[:,None]*(unit-refunit), axis=0)
            interaction = np.sum(((speed-refspeed)*dt)[:,None]*(unit-refunit), axis=0)
            row = dict(scenario=scenario['id'], estimator=name,
                drift_pct=ev.metrics['drift_percentage'], final_error_m=ev.metrics['final_position_error_m'],
                speed_mae_mps=float(np.mean(abs(speed-refspeed))), speed_bias_mps=float(np.mean(speed-refspeed)),
                moving_yaw_mae_deg=float(np.mean(abs(np.rad2deg(dyaw[moving])))),
                initial_yaw_error_deg=float(np.rad2deg(dyaw[0])), final_yaw_error_deg=float(np.rad2deg(dyaw[-1])),
                speed_component_m=float(np.linalg.norm(speed_vec)), yaw_component_m=float(np.linalg.norm(yaw_vec)),
                interaction_component_m=float(np.linalg.norm(interaction)),
                stationary_updates=int(t.stationary_update_accepted.sum()),
                false_stationary_updates=int((t.stationary_update_accepted.to_numpy() & (refspeed>2)).sum()),
                mean_accel_mps2=float(t.conditioned_forward_acceleration_mps2.mean()),
                final_residual_accel_bias_mps2=float(t.accel_bias_estimate_mps2.iloc[-1]),
                dt_min_s=float(dt.min()),dt_max_s=float(dt.max()),
                ml_accepted=int(t.ml_update_accepted.sum()),ml_ood_skipped=int(t.ml_update_skipped_ood.sum()),
                init_speed_mps=cal.initialization.initial_speed_mps, reference_start_speed_mps=float(refspeed[0]),
                gnss_solution_age_s=cal.initialization.gnss_solution_change_age_s,
                yaw_anchor_dispersion_deg=cal.yaw_dispersion_deg, bias_reliable=cal.bias_calibration_reliable)
            rows.append(row)
            t.to_csv(out / (scenario['id']+'_'+name+'.csv'), index=False)
    pd.DataFrame(rows).to_csv(out/'budget.csv', index=False)
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == '__main__':
    main()
