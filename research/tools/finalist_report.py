"""Generate measured exploratory evidence without modifying historical artifacts."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/finalist_20261005'
CASES=['S1_10_STEADY','S1_30_TURNING','S1_60_STOP_GO','S1_120_HIGHER_SPEED']


def markdown(frame):
    # No optional tabulate dependency.
    rows=['| '+' | '.join(frame.columns)+' |','|'+'|'.join(['---']*len(frame.columns))+'|']
    for row in frame.itertuples(index=False,name=None):
        rows.append('| '+' | '.join(f'{v:.3f}' if isinstance(v,float) else str(v) for v in row)+' |')
    return '\n'.join(rows)


def main():
    plots=OUT/'plots'
    plots.mkdir(exist_ok=True)
    plt.rcParams.update({'font.size':13,'figure.dpi':150})
    a=pd.read_csv(OUT/'feedback_bias_ablation/ablation.csv')
    all_ablations=pd.concat([pd.read_csv(OUT/f'{s}_ablation/ablation.csv').assign(suite=s)
                            for s in ('initialization','feedback_bias','turn_constraint')],ignore_index=True)
    all_ablations.to_csv(OUT/'all_ablations.csv',index=False)
    aggregate=all_ablations.loc[all_ablations.scenario.isin(CASES)].groupby(['suite','candidate','mode']).drift_pct.agg(['mean','median','min','max']).reset_index()
    aggregate.to_csv(OUT/'ablation_aggregates.csv',index=False)
    b=a.loc[a.scenario.isin(CASES)&(a.candidate=='baseline')&(a['mode']=='hybrid')].set_index('scenario').loc[CASES]
    c=a.loc[a.scenario.isin(CASES)&(a.candidate=='yaw_course_bias')&(a['mode']=='hybrid')].set_index('scenario').loc[CASES]
    classical=a.loc[a.scenario.isin(CASES)&(a.candidate=='yaw_course_bias')&(a['mode']=='classical')].set_index('scenario').loc[CASES]
    comparison=pd.DataFrame({'Window (s)':[10,30,60,120],'Baseline hybrid %':b.drift_pct.values,
        'Candidate classical %':classical.drift_pct.values,'Candidate hybrid %':c.drift_pct.values,
        'Candidate final error m':c.final_error_m.values,'Candidate mean error m':c.mean_error_m.values,
        'Candidate RMSE m':c.rmse_m.values,'Candidate P95 m':c.p95_m.values,'Candidate maximum m':c.max_error_m.values})
    comparison.to_csv(OUT/'comparison.csv',index=False)
    fig,ax=plt.subplots(figsize=(10,5))
    x=np.arange(4)
    ax.bar(x-.18,b.drift_pct,.36,label='Public baseline hybrid')
    ax.bar(x+.18,c.drift_pct,.36,label='Exploratory heading candidate')
    ax.axhline(10,color='black',ls='--',label='10% target')
    ax.set(xticks=x,xticklabels=['10 s','30 s','60 s','120 s'],ylabel='Final relative error / reference distance (%)',title='Locked IO-VNBD windows — research, not phone accuracy')
    ax.legend(fontsize=10);fig.tight_layout();fig.savefig(plots/'old_vs_candidate.png');plt.close(fig)
    speed_rows=[]
    for scenario in CASES:
        base=pd.read_csv(OUT/f'baseline/{scenario}/scenarios/{scenario.lower()}/timeseries.csv')
        candidate=pd.read_csv(OUT/f'feedback_bias_ablation/{scenario}/hybrid.csv')
        fig,axes=plt.subplots(2,2,figsize=(14,10))
        ax=axes[0,0]
        ax.plot(base.reference_relative_x_m,base.reference_relative_y_m,label='VBOX offline reference',color='black')
        for prefix,label in [('raw','Raw'),('ekf','Baseline EKF'),('hybrid','Baseline hybrid')]:
            ax.plot(base[f'{prefix}_relative_x_m'],base[f'{prefix}_relative_y_m'],label=label)
        ax.plot(candidate.predicted_relative_x_m,candidate.predicted_relative_y_m,label='Heading candidate',ls='--')
        ax.set(xlabel='East (m)',ylabel='North (m)');ax.axis('equal');ax.legend(fontsize=9)
        t=base.blackout_elapsed_s
        axes[0,1].plot(t,base.hybrid_position_error_m,label='Baseline')
        axes[0,1].plot(t,candidate.relative_position_error_m,label='Candidate')
        axes[0,1].set(xlabel='Blackout elapsed (s)',ylabel='Position error (m)');axes[0,1].legend()
        for field,label in [('reference_speed_mps','VBOX'),('ekf_speed_mps','Classical'),('hybrid_speed_mps','Hybrid')]:
            axes[1,0].plot(t,base[field],label=label)
        axes[1,0].plot(t,candidate.estimated_speed_mps,label='Candidate',ls='--')
        axes[1,0].set(xlabel='Blackout elapsed (s)',ylabel='Speed (m/s)');axes[1,0].legend(fontsize=9)
        axes[1,1].plot(t,candidate.horizontal_position_sigma_m,label='Candidate engineering sigma')
        axes[1,1].plot(t,candidate.relative_position_error_m,label='Candidate actual error')
        axes[1,1].set(xlabel='Blackout elapsed (s)',ylabel='Metres (sigma is not calibrated)');axes[1,1].legend(fontsize=9)
        fig.suptitle(scenario+' — offline exploratory comparison');fig.tight_layout();fig.savefig(plots/f'{scenario}.png');plt.close(fig)
        for name,speed in [('classical',base.ekf_speed_mps),('baseline_hybrid',base.hybrid_speed_mps),('candidate_hybrid',candidate.estimated_speed_mps)]:
            ref=base.reference_speed_mps.to_numpy()
            error=speed.to_numpy()-ref
            for group,mask in [('all',np.ones(len(ref),dtype=bool)),('under_2',ref<2),('2_to_10',(ref>=2)&(ref<10)),('over_10',ref>=10)]:
                if not mask.any():continue
                e=error[mask]
                corr=float(np.corrcoef(speed.to_numpy()[mask],ref[mask])[0,1]) if np.std(ref[mask])>1e-8 and np.std(speed.to_numpy()[mask])>1e-8 else None
                speed_rows.append(dict(scenario=scenario,estimator=name,reference_speed_bin=group,n=int(mask.sum()),mae=float(np.mean(abs(e))),rmse=float(np.sqrt(np.mean(e*e))),p95=float(np.percentile(abs(e),95)),bias=float(np.mean(e)),correlation=corr))
    pd.DataFrame(speed_rows).to_csv(OUT/'speed_metrics.csv',index=False)
    lines=['# NavGhost engineering evidence — 2026-10-05','',
      '**MORE ENGINEERING REQUIRED. App, signed build and website remain version 2.4.0.**','',
      'The four baseline windows reproduced before changes. Historical outputs, configurations, scaler and checkpoint remain intact. Seven causal candidate variants were evaluated on the same windows and existing development intervals. These are exploratory engineering comparisons, not newly blind holdouts. No reference was supplied to a runtime estimator.','',
      '## Full standard comparison','',markdown(comparison),'',
      f'Baseline: 0/4 below 10%; mean {b.drift_pct.mean():.3f}%, median {b.drift_pct.median():.3f}%, worst {b.drift_pct.max():.3f}%. Candidate: {int((c.drift_pct<10).sum())}/4; mean {c.drift_pct.mean():.3f}%, median {c.drift_pct.median():.3f}%, worst {c.drift_pct.max():.3f}%. Candidate is NOT deployed to Android.','',
      '## Root causes and decisions','',
      '- Baseline 10 s moving yaw MAE is 11.883 degrees; diagnostic integrated heading-error component is 32.277 m. At 30 s, initial heading error is -24.677 degrees and GNSS speed initialization is stale. At 60 s, speed and residual acceleration bias dominate; stationary updates were not false-positive against reference speed above 2 m/s. At 120 s, hybrid signed speed bias is -4.004 m/s and initial yaw error is -26.697 degrees. Diagnostic components are interacting vectors, not additive causal percentages.','- Last distinct pre-loss fixes are 4–8 s old. Measured sample intervals remain 0.093–0.107 s; no large timestamp gap explains these failures.','- Latest moving phone course plus pre-loss gyro propagation/bias improves all four source-domain hybrid windows. It still worsens one development case (10.167% to 14.633%) and the MTV30 transfer case. Retain as research, not an Android accuracy claim.','- Speed extrapolation and moving accelerometer-bias estimates regress other windows; disabled. Turning-velocity pseudo-measurements regress development and long-window results; disabled.','- Training uses independent classical speed, while original hybrid inference feeds corrected speed back. A separate classical prior removes that mismatch but makes DEV2020 much worse (10.167% to 159.758%). It is disabled; replacing the model or deploying this change without retraining/validation would be unjustified.','- Hard OOD from the start reproduces classical output in a new test. This does not prove recovery to a never-corrected classical trajectory after previously accepted ML updates, nor guarantee that an in-distribution prediction improves truth.','',
      '## Runtime and device status','',
      'Android core navigation remains the existing EKF/GRU/recovery pipeline. A new generic SI-unit input adapter and Android forwarding adapter are tested. Synthetic host replay: 20,000 inputs at a 200 Hz equivalent cadence, 1,000 normalized engine updates at 10 Hz. One host run averaged 0.01171246 ms/input, P95 0.0239 ms/input, 85,379 inputs/s. This is not physical FOG, native 200 Hz estimator accuracy, phone timing, battery, or memory evidence. Missing attitude remains missing; no synthetic attitude is invented.','',
      '293 Python tests and 194 Kotlin tests pass; debug build and Android lint pass. A first lint run crashed internally during a concurrent source edit; a stable rerun passed. No test was removed. A source-boundary test was updated to verify the new forwarding path and retained publication ordering.','',
      'ADB and Windows device enumeration currently expose no phone. No installation, app-data clearing, runtime GNSS acquisition, stationary blackout, recovery, or phone profiling was performed this run. Existing physical observations are historical only.','',
      '## Maps and field work','',
      'Road matching remains RESEARCH ONLY: existing frozen evidence shows branch-selection regressions, and no new safe runtime benefit was established. No lane-level truth exists. The existing automatic 10/30/60/120 s field presets remain available; no drive was fabricated.','',
      '**MOVING VEHICLE VALIDATION REQUIRED**','',
      'While parked: securely mount the phone, grant precise location, start live sensing outdoors, and arm the automatic preset. Drive normally without driver interaction; the app waits for fresh GNSS and alignment. A passenger may operate controls. After parking, stop and export the session ZIP to a private directory. Run tools/validate_phase11_android_session.py on that directory. Same-phone GNSS is a proxy, not survey-grade truth.','',
      '## Reproduction','',
      'Use the existing environment: tools/finalist_error_budget.py; tools/finalist_initialization_ablation.py --suite initialization (or feedback_bias / turn_constraint); tools/run_phase8_validation.py --output results/finalist_20261005/cross_device_baseline; tools/finalist_cross_device_candidate.py; tools/finalist_report.py. Source datasets must be acquired separately. Do not put private phone traces in Git.','',
      'All failed candidates remain in all_ablations.csv; aggregates include median and worst-case. speed_metrics.csv contains MAE/RMSE/P95/bias/correlation and speed bins. Cross-device baseline/candidate directories retain all four windows, including the zero-distance case with undefined drift.']
    (OUT/'ENGINEERING_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    files=list((ROOT/'configs').rglob('*.json'))+[ROOT/'models/phase5/io_vnbd_s1/velocity_gru.pt']
    (OUT/'artifact_hashes.json').write_text(json.dumps({str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},indent=2))
    print(comparison.to_string(index=False))


if __name__=='__main__':main()
