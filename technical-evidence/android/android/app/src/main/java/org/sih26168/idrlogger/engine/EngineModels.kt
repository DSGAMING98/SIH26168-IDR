package org.sih26168.idrlogger.engine

enum class LocalizationMode {
    WAITING_FOR_GNSS,
    CALIBRATING,
    CALIBRATION_REQUIRED,
    GNSS_ACTIVE,
    GNSS_DEGRADED,
    IDR_ACTIVE,
    GNSS_VERIFYING,
    GNSS_RECOVERING,
    ERROR,
}

enum class AlignmentState { CALIBRATING, READY, DEGRADED }

enum class MotionState { INITIALIZING, MOVING, LIKELY_STATIONARY }

enum class MlRuntimeState { ML_WARMING, ML_ACCEPTED, ML_OOD_LIMITED, ML_REJECTED, ML_UNAVAILABLE }

enum class ConfidenceLevel { HIGH, MEDIUM, LOW, UNAVAILABLE }

data class NavigationState(
    val sequenceId: Long = -1L,
    val monotonicTimestampNs: Long = 0L,
    val latitudeDeg: Double? = null,
    val longitudeDeg: Double? = null,
    val eastM: Double = 0.0,
    val northM: Double = 0.0,
    val speedMps: Double = 0.0,
    val headingDeg: Double = 0.0,
    val horizontalUncertaintyM: Double? = null,
    val confidence: ConfidenceLevel = ConfidenceLevel.UNAVAILABLE,
    val localizationMode: LocalizationMode = LocalizationMode.WAITING_FOR_GNSS,
    val alignmentState: AlignmentState = AlignmentState.CALIBRATING,
    val alignmentProgress: Double = 0.0,
    val motionState: MotionState = MotionState.INITIALIZING,
    val mlState: MlRuntimeState = MlRuntimeState.ML_WARMING,
    val mlResidualMps: Double? = null,
    val mlOodExceedance: Double? = null,
    val drDurationSeconds: Double = 0.0,
    val gnssInnovationM: Double? = null,
    val lastCorrectionM: Double = 0.0,
    val engineAverageMs: Double = 0.0,
    val engineP95Ms: Double = 0.0,
    val message: String = "Waiting for a trusted GNSS fix",
)

data class TrajectoryPoint(
    val eastM: Double,
    val northM: Double,
    val localizationMode: LocalizationMode,
)

data class NavigationSnapshot(
    val state: NavigationState = NavigationState(),
    val trajectory: List<TrajectoryPoint> = emptyList(),
    val isDemoReplay: Boolean = false,
)

data class ConditionedMotion(
    val forwardAccelerationMps2: Double,
    val leftAccelerationMps2: Double,
    val yawRateRadps: Double,
    val deviceHeadingRad: Double?,
    val gyroMagnitudeRadps: Double,
    val gravityMagnitudeMps2: Double,
    val magneticMagnitudeUt: Double,
    val accelerationRmsMps2: Double,
    val gyroRmsRadps: Double,
    val motionState: MotionState,
    val attitudeAvailable: Boolean,
)
