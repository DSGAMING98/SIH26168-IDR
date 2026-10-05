"""Experimental pre-loss initialization; no blackout/reference input is accepted.

Anchor yaw to the last moving phone course, then propagate measured gyro rather
than a potentially disturbed magnetic azimuth. Optional speed extrapolation and
moving bias estimates use only intervals between distinct pre-loss phone fixes.
These candidates are not enabled in the frozen baseline.
"""
from dataclasses import replace
import numpy as np
from .calibrated_dr import build_phase4_calibration, _distinct_navigation_rows, _vehicle_components


def reinitialize(sensor_history, gnss_history, start_s, settings, *, speed=False, moving_bias=False, course_bias=False):
    cal = build_phase4_calibration(sensor_history, gnss_history, start_s, settings)
    fixes = _distinct_navigation_rows(gnss_history)
    fixes = fixes.loc[fixes.elapsed_s >= start_s-settings.calibration_window_s]
    if fixes.empty:
        return cal
    last = fixes.iloc[-1]
    accel_bias = cal.accelerometer_bias_forward_mps2
    gyro_bias = cal.gyroscope_bias_radps
    components, _, _, _ = _vehicle_components(sensor_history)
    times = sensor_history.elapsed_s.to_numpy(float)
    dt = np.diff(times, prepend=times[0])
    accel = components[:, 0]
    gyro = sensor_history[f'gyroscope_{settings.gyro_yaw_axis}_radps'].to_numpy(float)
    if course_bias:
        rates = []
        for (_, first), (_, second) in zip(fixes.iloc[:-1].iterrows(), fixes.iloc[1:].iterrows()):
            span = float(second.elapsed_s-first.elapsed_s)
            mask = (times>first.elapsed_s) & (times<=second.elapsed_s)
            if span < 1 or not mask.any() or min(first.gps_speed_mps,second.gps_speed_mps)<settings.moving_speed_threshold_mps:
                continue
            angle = np.deg2rad((second.gps_orientation_deg-first.gps_orientation_deg+180)%360-180)
            estimate = (np.sum(gyro[mask]*dt[mask])-angle/settings.gyro_course_scale)/span
            if abs(estimate)<=settings.maximum_gyro_bias_radps:
                rates.append(estimate)
        if len(rates)>=3:
            gyro_bias = float(np.median(rates))
    if moving_bias:
        estimates = []
        for (_, first), (_, second) in zip(fixes.iloc[:-1].iterrows(), fixes.iloc[1:].iterrows()):
            span = float(second.elapsed_s-first.elapsed_s)
            mask = (times>first.elapsed_s) & (times<=second.elapsed_s)
            if span < 1 or not mask.any():
                continue
            estimate = (np.sum(accel[mask]*dt[mask])-(second.gps_speed_mps-first.gps_speed_mps))/span
            if abs(estimate)<=settings.maximum_accel_bias_mps2:
                estimates.append(estimate)
        if len(estimates)>=3:
            accel_bias = float(np.median(estimates))
    mask = times>float(last.elapsed_s)
    heading = cal.initial_calibrated_heading_deg
    # Course is unreliable at low speed; retain existing calibration then.
    if last.gps_speed_mps >= settings.moving_speed_threshold_mps:
        heading = float((last.gps_orientation_deg + np.degrees(np.sum(
            settings.gyro_course_scale*(gyro[mask]-gyro_bias)*dt[mask])))%360)
    initial_speed = cal.initialization.initial_speed_mps
    if speed:
        initial_speed = float(max(0, initial_speed+np.sum((accel[mask]-accel_bias)*dt[mask])))
    initialization = replace(cal.initialization, initial_heading_deg=heading,
        initial_speed_mps=initial_speed, heading_source='causal latest moving phone course plus gyro')
    return replace(cal, initialization=initialization, initial_calibrated_heading_deg=heading,
        accelerometer_bias_forward_mps2=accel_bias, gyroscope_bias_radps=gyro_bias)
