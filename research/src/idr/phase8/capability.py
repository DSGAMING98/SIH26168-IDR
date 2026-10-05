"""Machine-readable local Phase 8 dataset capability audit."""

from __future__ import annotations


CAPABILITY_ROWS: tuple[dict[str, object], ...] = (
    {
        "dataset": "IO-VNBD S1",
        "local_status": "BASELINE",
        "platform": "vehicle smartphone plus synchronized VBOX reference",
        "runtime_imu": True,
        "runtime_gnss": True,
        "trajectory_reference": True,
        "core_phase5_compatible": True,
        "phase6_map_compatible": True,
        "phase7_reacquisition_compatible": True,
        "reason": "Validated source-domain baseline; not rerun as a Phase 8 target.",
    },
    {
        "dataset": "Google Smartphone Decimeter 2022",
        "local_status": "PARTIALLY COMPATIBLE",
        "platform": "vehicle smartphone",
        "runtime_imu": True,
        "runtime_gnss": True,
        "trajectory_reference": True,
        "core_phase5_compatible": True,
        "phase6_map_compatible": False,
        "phase7_reacquisition_compatible": False,
        "reason": "Best local cross-dataset target. WLS positions have no defensible per-fix accuracy for the frozen Phase 7 validator; the S1 road graph is geographically inapplicable.",
    },
    {
        "dataset": "WHU Smartphone Dataset",
        "local_status": "REFERENCE-ONLY",
        "platform": "smartphone GNSS plus separate reference",
        "runtime_imu": False,
        "runtime_gnss": True,
        "trajectory_reference": True,
        "core_phase5_compatible": False,
        "phase6_map_compatible": False,
        "phase7_reacquisition_compatible": False,
        "reason": "Local phone logs lack the accelerometer/gyroscope/magnetometer stream required by the frozen core estimator.",
    },
    {
        "dataset": "MoRPI",
        "local_status": "PARTIALLY COMPATIBLE",
        "platform": "smartphone on RC robot",
        "runtime_imu": True,
        "runtime_gnss": False,
        "trajectory_reference": False,
        "core_phase5_compatible": False,
        "phase6_map_compatible": False,
        "phase7_reacquisition_compatible": False,
        "reason": "Local files provide acceleration/gyroscope only; magnetometer, GNSS initialization, mounting convention, and time-resolved reference are absent.",
    },
    {
        "dataset": "PPC Dataset",
        "local_status": "UNUSABLE LOCALLY",
        "platform": "vehicle with dedicated IMU/GNSS",
        "runtime_imu": False,
        "runtime_gnss": False,
        "trajectory_reference": False,
        "core_phase5_compatible": False,
        "phase6_map_compatible": False,
        "phase7_reacquisition_compatible": False,
        "reason": "Only repository documentation/LFS metadata are local; expected run payloads are absent.",
    },
    {
        "dataset": "GREAT Dataset",
        "local_status": "UNUSABLE LOCALLY",
        "platform": "dedicated vehicle multisensor platform",
        "runtime_imu": False,
        "runtime_gnss": False,
        "trajectory_reference": False,
        "core_phase5_compatible": False,
        "phase6_map_compatible": False,
        "phase7_reacquisition_compatible": False,
        "reason": "Local repository contains documentation, figures, and tools but no usable sensor/reference sequence payload.",
    },
)


CAPABILITY_DETAILS: dict[str, dict[str, object]] = {
    "IO-VNBD S1": {
        "timestamps": "yes; synchronized 10 Hz elapsed/session timestamps",
        "accelerometer": "yes", "gyroscope": "yes", "magnetometer": "yes",
        "gravity": "yes", "orientation": "yes; phone sensor orientation",
        "gnss_latitude_longitude": "yes", "gnss_speed": "yes; values behave as m/s despite Kmh label",
        "gnss_course_heading": "yes", "altitude": "yes",
        "reference_position": "yes; synchronized VBOX evaluation reference",
        "reference_velocity": "yes", "reference_orientation": "yes",
        "device_metadata": "smartphone stream S-S1 and VBOX V-S1",
        "native_rates": "approximately 10 Hz phone and reference",
        "sensor_frame": "documented mounted phone; Phase 4 verified +X travel projection and data-specific gyro-y course sign",
        "coordinate_frame": "latitude/longitude datum and EPSG unspecified; local spherical tangent frame used",
        "units": "verified in Phase 1; known mislabeled speed/height columns retained in documentation",
        "ground_truth_suitability": "suitable synchronized evaluation reference; not claimed survey-grade absolute truth",
    },
    "Google Smartphone Decimeter 2022": {
        "timestamps": "yes; UTC milliseconds",
        "accelerometer": "yes; UncalAccel", "gyroscope": "yes; UncalGyro", "magnetometer": "yes; UncalMag",
        "gravity": "not native; causally estimated from accelerometer",
        "orientation": "header exists in supplemental log but selected device_imu streams do not provide orientation rows",
        "gnss_latitude_longitude": "yes; runtime WLS ECEF converted to geodetic",
        "gnss_speed": "not native in device_gnss; causally derived from past WLS positions",
        "gnss_course_heading": "not native in device_gnss; causally derived from past WLS positions",
        "altitude": "WLS ECEF supports conversion but altitude is not required/exposed by the Phase 8 adapter",
        "reference_position": "yes; ground_truth.csv latitude/longitude",
        "reference_velocity": "yes; SpeedMps", "reference_orientation": "yes; BearingDegrees",
        "device_metadata": "session path and phone model",
        "native_rates": "selected devices: accelerometer/gyro ~52.63 Hz, magnetometer ~100 Hz, WLS/reference ~1 Hz",
        "sensor_frame": "Android device axes; mounting axis not documented, inferred causally from pre-blackout horizontal IMU dynamics",
        "coordinate_frame": "runtime GNSS WLS ECEF converted with WGS84 ellipsoid; reference latitude/longitude",
        "units": "supplemental headers explicitly state m/s^2, rad/s, and microtesla",
        "ground_truth_suitability": "suitable for offline trajectory/speed evaluation; WLS has no per-fix accuracy for frozen Phase 7",
    },
    "WHU Smartphone Dataset": {
        "timestamps": "yes in GNSS logs/reference files",
        "accelerometer": "absent from local phone logs", "gyroscope": "absent from local phone logs",
        "magnetometer": "absent from local phone logs", "gravity": "absent", "orientation": "UNKNOWN",
        "gnss_latitude_longitude": "yes", "gnss_speed": "available in GNSS message forms where populated",
        "gnss_course_heading": "UNKNOWN", "altitude": "available in GGA where populated",
        "reference_position": "separate Ground Truth files present", "reference_velocity": "UNKNOWN",
        "reference_orientation": "UNKNOWN", "device_metadata": "four smartphones described by local documentation",
        "native_rates": "GNSS rates vary/UNKNOWN from inspected local logs; no local IMU cadence",
        "sensor_frame": "not applicable for missing local IMU", "coordinate_frame": "GNSS geographic formats; exact cross-file alignment semantics not established",
        "units": "GNSS message conventions only; missing IMU units", "ground_truth_suitability": "potential GNSS/reference analysis only; not fair for frozen inertial pipeline",
    },
    "MoRPI": {
        "timestamps": "yes; time column", "accelerometer": "yes; f_x/f_y/f_z", "gyroscope": "yes; g_x/g_y/g_z",
        "magnetometer": "absent", "gravity": "not supplied", "orientation": "absent",
        "gnss_latitude_longitude": "absent", "gnss_speed": "absent", "gnss_course_heading": "absent", "altitude": "absent",
        "reference_position": "no time-resolved compatible trajectory found", "reference_velocity": "absent", "reference_orientation": "absent",
        "device_metadata": "Samsung S6/S8 on RC robot", "native_rates": "approximately 100 Hz",
        "sensor_frame": "axis meanings/mounting not established by inspected local documentation", "coordinate_frame": "UNKNOWN",
        "units": "column names do not establish all required units unambiguously", "ground_truth_suitability": "not suitable for current trajectory metrics",
    },
    "PPC Dataset": {
        "timestamps": "documented but payload absent", "accelerometer": "documented ADIS16505-2; payload absent",
        "gyroscope": "documented; payload absent", "magnetometer": "not established", "gravity": "not supplied",
        "orientation": "reference documentation only", "gnss_latitude_longitude": "documented; payload absent",
        "gnss_speed": "documented source but payload absent", "gnss_course_heading": "documented source but payload absent", "altitude": "documented source but payload absent",
        "reference_position": "POS LV documented; payload absent", "reference_velocity": "documented; payload absent", "reference_orientation": "documented; payload absent",
        "device_metadata": "dedicated vehicle platform", "native_rates": "documentation: IMU 100 Hz, GNSS 5 Hz",
        "sensor_frame": "documentation: X forward, Y right, Z down", "coordinate_frame": "cannot validate without payload",
        "units": "documented but cannot validate without payload", "ground_truth_suitability": "unavailable locally",
    },
    "GREAT Dataset": {
        "timestamps": "documentation only; sequence payload absent", "accelerometer": "documentation only", "gyroscope": "documentation only",
        "magnetometer": "UNKNOWN", "gravity": "UNKNOWN", "orientation": "documentation only/UNKNOWN locally",
        "gnss_latitude_longitude": "documentation only", "gnss_speed": "documentation only", "gnss_course_heading": "documentation only", "altitude": "documentation only",
        "reference_position": "documentation only", "reference_velocity": "documentation only", "reference_orientation": "documentation only",
        "device_metadata": "dedicated vehicle multisensor platform", "native_rates": "documentation mentions 100/200 Hz IMU variants",
        "sensor_frame": "cannot validate without payload", "coordinate_frame": "cannot validate without payload", "units": "cannot validate without payload",
        "ground_truth_suitability": "unavailable locally",
    },
}


def capability_rows() -> list[dict[str, object]]:
    return [{**row, **CAPABILITY_DETAILS[str(row["dataset"])]} for row in CAPABILITY_ROWS]


def require_core_compatible(dataset: str) -> dict[str, object]:
    """Return a capability record or reject unsupported data explicitly."""

    try:
        row = next(item for item in CAPABILITY_ROWS if item["dataset"] == dataset)
    except StopIteration as error:
        raise ValueError(f"Dataset was not audited: {dataset}") from error
    if not bool(row["core_phase5_compatible"]):
        raise ValueError(f"Dataset is not core Phase 5 compatible: {dataset}: {row['reason']}")
    return dict(row)
