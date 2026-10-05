"""Run the existing locked cross-device evaluator with explicit candidate initialization.

All outputs are exploratory, NOT the frozen Phase 8 result. This wrapper keeps
the dataset loader, reference isolation, windows, model and metric code identical.
"""
from dataclasses import replace
import sys
import run_phase8_validation as evaluator
from idr.causal_reinitialization import reinitialize

original_prepare=evaluator.prepare_runtime


def prepare_candidate(blackout,phase4_settings,**kwargs):
    prepared=original_prepare(blackout,phase4_settings,**kwargs)
    calibration=reinitialize(prepared.sensor_history,prepared.gnss_history,blackout.start_s,
                             phase4_settings,course_bias=True)
    return replace(prepared,calibration=calibration,
                   assumptions={**prepared.assumptions,'candidate':'latest course plus pre-loss gyro bias; exploratory, not frozen Phase 8'})


if __name__=='__main__':
    evaluator.prepare_runtime=prepare_candidate
    sys.argv=[sys.argv[0],'--output','results/finalist_20261005/cross_device_candidate']
    evaluator.main()
