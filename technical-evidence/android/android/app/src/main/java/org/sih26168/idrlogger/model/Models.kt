package org.sih26168.idrlogger.model

data class Vector3(val x: Double, val y: Double, val z: Double)

data class Quaternion(val x: Double, val y: Double, val z: Double, val w: Double)

enum class SensorKind(val csvName: String) {
    ACCELEROMETER("accelerometer"),
    GYROSCOPE("gyroscope"),
    MAGNETOMETER("magnetometer"),
    GRAVITY("gravity"),
    ROTATION_VECTOR("rotation_vector"),
}

enum class GnssStatus {
    WAITING_FOR_FIRST_FIX,
    FRESH,
    STALE,
    INVALID,
    PROVIDER_DISABLED,
    SIMULATED_BLACKOUT,
}

enum class PhysicalGnssState { NONE, FRESH, STALE }

enum class RuntimeGnssAvailability { AVAILABLE, MASKED, UNAVAILABLE }

enum class MlOodState {
    NOT_EVALUATED,
    IN_DISTRIBUTION,
    SOFT_OOD,
    HARD_OOD,
}

data class TimedSensorValue(
    val kind: SensorKind,
    val monotonicTimestampNs: Long,
    val values: List<Double>,
    val accuracy: Int,
)

data class PhysicalGnssFix(
    val monotonicTimestampNs: Long,
    val wallClockUtc: String,
    val latitudeDeg: Double,
    val longitudeDeg: Double,
    val altitudeM: Double?,
    val speedMps: Double?,
    val bearingDeg: Double?,
    val accuracyM: Double?,
    val verticalAccuracyM: Double?,
    val speedAccuracyMps: Double?,
    val bearingAccuracyDeg: Double?,
    val provider: String,
)

data class RuntimeGnssFix(
    val latitudeDeg: Double,
    val longitudeDeg: Double,
    val altitudeM: Double?,
    val speedMps: Double?,
    val bearingDeg: Double?,
    val accuracyM: Double?,
    val verticalAccuracyM: Double?,
    val speedAccuracyMps: Double?,
    val bearingAccuracyDeg: Double?,
    val provider: String,
)

data class GnssRuntimeState(
    val status: GnssStatus,
    val ageSeconds: Double?,
    val isFresh: Boolean,
    val runtimeFix: RuntimeGnssFix?,
)

data class GnssDiagnosticsSnapshot(
    val physicalCallbackCount: Long = 0L,
    val latestPhysicalCallbackAgeSeconds: Double? = null,
    val lastPhysicalGnssTimestampNs: Long? = null,
    val firstValidFixTimestampNs: Long? = null,
    val timeToFirstFixSeconds: Double? = null,
    val satellitesVisible: Int? = null,
    val satellitesUsedInFix: Int? = null,
    val gnssStatusAvailable: Boolean = false,
    val blackoutMasksRealFix: Boolean = false,
    val physicalFixState: PhysicalGnssState = PhysicalGnssState.NONE,
    val runtimeGnssAvailability: RuntimeGnssAvailability = RuntimeGnssAvailability.UNAVAILABLE,
    val hasAcquiredRealFixThisSession: Boolean = false,
    val blackoutMasksFreshFix: Boolean = false,
)

data class SensorAvailability(
    val accelerometer: Boolean,
    val gyroscope: Boolean,
    val magnetometer: Boolean,
    val gravity: Boolean,
    val rotationVector: Boolean,
    val gpsProvider: Boolean,
)

data class LiveIdrSample(
    val sequenceId: Long,
    val elapsedSeconds: Double,
    val monotonicTimestampNs: Long,
    val wallClockUtc: String,
    val accelerometer: Vector3?,
    val gyroscope: Vector3?,
    val magnetometer: Vector3?,
    val gravity: Vector3?,
    val rotation: Quaternion?,
    val gnss: RuntimeGnssFix?,
    val gnssFixAgeSeconds: Double?,
    val gnssIsFresh: Boolean,
    val gnssStatus: GnssStatus,
    val simulatedBlackout: Boolean,
    val gnssDiagnostics: GnssDiagnosticsSnapshot,
    val availability: SensorAvailability,
    val mlOodState: MlOodState = MlOodState.NOT_EVALUATED,
    val mlFeatureExceedance: Double? = null,
    val mlCorrectionAccepted: Boolean? = null,
)

data class SensorRateSnapshot(
    val accelerometerHz: Double,
    val gyroscopeHz: Double,
    val magnetometerHz: Double,
    val gravityHz: Double,
    val rotationVectorHz: Double,
    val normalizedHz: Double,
)

data class LoggerStatus(
    val recording: Boolean = false,
    val elapsedSeconds: Double = 0.0,
    val gnssStatus: GnssStatus = GnssStatus.WAITING_FOR_FIRST_FIX,
    val gnssAgeSeconds: Double? = null,
    val latitudeDeg: Double? = null,
    val longitudeDeg: Double? = null,
    val speedMps: Double? = null,
    val bearingDeg: Double? = null,
    val simulatedBlackout: Boolean = false,
    val gnssDiagnostics: GnssDiagnosticsSnapshot = GnssDiagnosticsSnapshot(),
    val availability: SensorAvailability = SensorAvailability(false, false, false, false, false, false),
    val rates: SensorRateSnapshot = SensorRateSnapshot(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    val sessionDirectory: String? = null,
    val message: String = "IDLE",
    val systemHealth: SystemHealthSnapshot = SystemHealthSnapshot(),
    val fieldTest: FieldTestStatus = FieldTestStatus(),
)

data class SystemHealthSnapshot(
    val batteryPercent: Double? = null,
    val batteryTemperatureC: Double? = null,
    val thermalStatus: String? = null,
    val foregroundServiceActive: Boolean = false,
    val loggerErrorCount: Int = 0,
)

enum class MountProfile { DASHBOARD, WINDSHIELD, CENTER_CONSOLE, HANDHELD_TEST, UNKNOWN }

enum class FieldTestPreset(val blackoutDurationSeconds: Int) {
    SHORT(10), MEDIUM(30), LONG(60), EXTENDED(120),
}

enum class FieldTestPhase { IDLE, WARMUP, WAITING_FOR_READY, BASELINE, BLACKOUT, RECOVERY, COMPLETE, CANCELLED }

data class FieldTestStatus(
    val testId: String? = null,
    val preset: FieldTestPreset? = null,
    val mountProfile: MountProfile = MountProfile.UNKNOWN,
    val phase: FieldTestPhase = FieldTestPhase.IDLE,
    val phaseElapsedSeconds: Double = 0.0,
    val phaseRemainingSeconds: Double? = null,
    val blackoutActive: Boolean = false,
    val safetyMessage: String = "Configure while parked. Do not operate the phone while driving.",
)
