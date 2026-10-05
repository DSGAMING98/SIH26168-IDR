"""Safety regressions for opt-in candidates; frozen production defaults stay intact."""
from dataclasses import replace
import numpy as np
import pytest
from test_phase5_hybrid import _sensor,_calibration,_phase4_settings,_hybrid_settings,_ood_bundle
from idr.hybrid.hybrid_idr import run_hybrid_estimator
from idr.causal_reinitialization import reinitialize


def test_independent_features_equal_classical_even_after_ml_updates():
    sensor=_sensor(60,1.0)
    settings=replace(_hybrid_settings(),independent_classical_prior=True,
                     ood_soft_exceedance=1e9,ood_hard_exceedance=1e10)
    pure=run_hybrid_estimator(sensor,_calibration(),_phase4_settings(),settings)
    hybrid=run_hybrid_estimator(sensor,_calibration(),_phase4_settings(),settings,_ood_bundle())
    np.testing.assert_array_equal(pure.feature_data,hybrid.feature_data)
    assert hybrid.data.ml_update_accepted.sum()>0


def test_hard_ood_from_start_equals_classical():
    sensor=_sensor(60,20.0)
    settings=replace(_hybrid_settings(),independent_classical_prior=True)
    pure=run_hybrid_estimator(sensor,_calibration(),_phase4_settings(),settings)
    hybrid=run_hybrid_estimator(sensor,_calibration(),_phase4_settings(),settings,_ood_bundle())
    assert hybrid.data.ml_update_skipped_ood.sum()>0
    fields=['estimated_x_m','estimated_y_m','estimated_speed_mps']
    np.testing.assert_array_equal(pure.data[fields],hybrid.data[fields])


def test_turn_constraint_does_not_divide_by_zero():
    result=run_hybrid_estimator(_sensor(60),_calibration(),_phase4_settings(),
        replace(_hybrid_settings(),turning_velocity_constraint=True))
    assert np.isfinite(result.data.select_dtypes(include=[np.number])).all().all()


def test_candidates_are_opt_in():
    assert not _hybrid_settings().independent_classical_prior
    assert not _hybrid_settings().turning_velocity_constraint


def test_reinitialization_rejects_reference_and_future():
    sensor=_sensor(10)
    sensor['velocity_kmh']=1.0
    with pytest.raises(ValueError,match='reference'):
        reinitialize(sensor,sensor,0.5,_phase4_settings())
    sensor=sensor.drop(columns='velocity_kmh')
    with pytest.raises(ValueError,match='blackout or future'):
        reinitialize(sensor,sensor,0.5,_phase4_settings())
