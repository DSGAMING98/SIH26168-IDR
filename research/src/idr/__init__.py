"""Core research utilities for the SIH26168 intelligent dead-reckoning project."""

from .io_vnbd import (
    DatasetIntegrityError,
    IOVNBDJourney,
    SchemaError,
    load_journey,
    sampling_statistics,
)
from .blackout import BlackoutWindow, ExperimentDataset, create_blackout_experiment
from .evaluation import (
    drift_percentage,
    geodetic_to_local_xy_m,
    great_circle_distance_m,
    local_xy_to_geodetic,
    path_distance_m,
    summarize_position_errors,
)
from .dead_reckoning import (
    PhoneInitialization,
    RawDRPrediction,
    build_phone_initialization,
    extract_blackout_sensor_data,
    integrate_raw_dead_reckoning,
)

__all__ = [
    "DatasetIntegrityError",
    "IOVNBDJourney",
    "SchemaError",
    "load_journey",
    "sampling_statistics",
    "BlackoutWindow",
    "ExperimentDataset",
    "create_blackout_experiment",
    "drift_percentage",
    "geodetic_to_local_xy_m",
    "great_circle_distance_m",
    "local_xy_to_geodetic",
    "path_distance_m",
    "summarize_position_errors",
    "PhoneInitialization",
    "RawDRPrediction",
    "build_phone_initialization",
    "extract_blackout_sensor_data",
    "integrate_raw_dead_reckoning",
]
