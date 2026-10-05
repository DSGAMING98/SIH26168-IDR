"""Evaluate fixed causal initialization candidates without changing frozen artifacts."""
import json
import argparse
import sys
from dataclasses import replace
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from idr.blackout import BlackoutWindow, create_blackout_experiment
from idr.io_vnbd import load_journey
from idr.calibrated_dr import Phase4Settings,build_phase4_calibration
from idr.causal_reinitialization import reinitialize
from idr.dead_reckoning import extract_blackout_sensor_data
from idr.hybrid.hybrid_idr import HybridSettings,run_hybrid_estimator,evaluate_hybrid_prediction
from idr.ml.velocity_model import load_velocity_bundle

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--suite',choices=('initialization','feedback_bias','turn_constraint'),default='turn_constraint')
    args=parser.parse_args()
    suites={
        'initialization':('baseline','yaw_anchor','yaw_speed','yaw_speed_bias'),
        'feedback_bias':('baseline','independent_prior','yaw_course_bias','yaw_course_bias_independent'),
        'turn_constraint':('baseline','turn_constraint','yaw_course_bias','yaw_course_bias_turn_constraint'),
    }
    read=lambda p:json.loads((ROOT/p).read_text())
    out=ROOT/f'results/finalist_20261005/{args.suite}_ablation'
    out.mkdir(parents=True,exist_ok=True)
    journey=load_journey('S1',project_root_path=ROOT)
    p4=Phase4Settings.from_dict(read('configs/phase4/io_vnbd_s1_classical.json'))
    settings=HybridSettings.from_dict(read('configs/phase5/io_vnbd_s1_ekf.json'))
    bundle=load_velocity_bundle(ROOT/'models/phase5/io_vnbd_s1/velocity_gru.pt')
    # Development intervals precede standard reporting. All are inside existing validation blocks.
    cases=[dict(id=f'DEV_{start}',start_s=start,duration_s=60) for start in (1120,2020,4000)]
    cases += [s for s in read('configs/blackouts/io_vnbd_s1.json')['scenarios'] if s.get('standard')]
    rows=[]
    for s in cases:
        window=BlackoutWindow(s['start_s'],s['duration_s'])
        experiment=create_blackout_experiment(journey,window)
        sensors=experiment.runtime.sensor_data
        sh=sensors.loc[sensors.elapsed_s<window.start_s]
        gh=experiment.runtime.gnss_observations
        gh=gh.loc[gh.elapsed_s<window.start_s]
        blackout=extract_blackout_sensor_data(experiment.runtime,window)
        for candidate in suites[args.suite]:
            cal=(build_phase4_calibration(sh,gh,window.start_s,p4) if candidate in ('baseline','turn_constraint','independent_prior') else
                 reinitialize(sh,gh,window.start_s,p4,course_bias='course_bias' in candidate,
                              speed=candidate.startswith('yaw_speed'),moving_bias=candidate=='yaw_speed_bias'))
            candidate_settings=replace(settings,turning_velocity_constraint='turn_constraint' in candidate,
                                       independent_classical_prior='independent' in candidate)
            for mode,model in [('classical',None),('hybrid',bundle)]:
                prediction=run_hybrid_estimator(blackout,cal,p4,candidate_settings,model,float(gh.gps_accuracy_m.iloc[-1]))
                ev=evaluate_hybrid_prediction(prediction,experiment.reference)
                if candidate=='yaw_course_bias':
                    target=out/s['id']
                    target.mkdir(parents=True,exist_ok=True)
                    ev.timeseries.to_csv(target/f'{mode}.csv',index=False)
                    (target/f'{mode}.json').write_text(json.dumps(ev.metrics,indent=2))
                rows.append(dict(scenario=s['id'],candidate=candidate,mode=mode,
                    drift_pct=ev.metrics['drift_percentage'],final_error_m=ev.metrics['final_position_error_m'],
                    rmse_m=ev.metrics['rmse_position_error_m'],speed_mae=ev.metrics['speed_mae_mps'],
                    mean_error_m=ev.metrics['mean_position_error_m'],p95_m=ev.metrics['p95_position_error_m'],
                    max_error_m=ev.metrics['maximum_position_error_m'],
                    initial_speed=cal.initialization.initial_speed_mps,initial_yaw=cal.initial_calibrated_heading_deg,
                    accel_bias=cal.accelerometer_bias_forward_mps2))
        pd.DataFrame(rows).to_csv(out/'ablation.csv',index=False)
        print(pd.DataFrame(rows[-8:]).to_string(index=False),flush=True)

if __name__=='__main__':
    main()
