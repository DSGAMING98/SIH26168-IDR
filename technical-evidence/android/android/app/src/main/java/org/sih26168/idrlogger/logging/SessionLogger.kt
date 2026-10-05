package org.sih26168.idrlogger.logging

import android.content.Context
import android.hardware.Sensor
import android.os.Build
import java.io.BufferedWriter
import java.io.File
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import org.sih26168.idrlogger.BuildConfig
import org.sih26168.idrlogger.engine.NavigationState
import org.sih26168.idrlogger.model.GnssDiagnosticsSnapshot
import org.sih26168.idrlogger.model.GnssStatus
import org.sih26168.idrlogger.model.FieldTestStatus
import org.sih26168.idrlogger.model.LiveIdrSample
import org.sih26168.idrlogger.model.PhysicalGnssFix
import org.sih26168.idrlogger.model.SensorAvailability
import org.sih26168.idrlogger.model.SensorRateSnapshot
import org.sih26168.idrlogger.model.SystemHealthSnapshot
import org.sih26168.idrlogger.model.TimedSensorValue

data class DeviceSensorInfo(
    val kind: String,
    val available: Boolean,
    val name: String?,
    val vendor: String?,
    val resolution: Float?,
    val maximumRange: Float?,
)

data class Phase11SessionSummary(
    val runtimeSampleCount: Long,
    val mlStateCounts: Map<String, Long>,
    val engineAverageMs: Double,
    val engineP95Ms: Double,
    val finalLocalizationState: String,
    val finalAlignmentState: String,
    val finalMotionState: String,
    val startSystemHealth: SystemHealthSnapshot,
    val endSystemHealth: SystemHealthSnapshot,
)

class SessionLogger(
    context: Context,
    private val originNs: Long,
    private val startWallClockMs: Long,
    private val requestedSamplingPeriodUs: Int,
    private val normalizedRateHz: Double,
    private val sensorInfo: List<DeviceSensorInfo>,
    private val availability: SensorAvailability,
    private val locationProvider: String,
    private val initialSystemHealth: SystemHealthSnapshot = SystemHealthSnapshot(),
) {
    val sessionDirectory: File
    private val imuWriter: BufferedWriter
    private val gnssWriter: BufferedWriter
    private val runtimeWriter: BufferedWriter
    private val idrWriter: BufferedWriter
    private val eventWriter: BufferedWriter
    private var rawSequence = 0L
    private var gnssSequence = 0L
    private var pendingWrites = 0
    private var closed = false
    private var fieldTestStatus = FieldTestStatus()

    init {
        val timestamp = DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss")
            .withZone(ZoneOffset.UTC)
            .format(Instant.ofEpochMilli(startWallClockMs))
        val device = "${Build.MANUFACTURER}_${Build.MODEL}".replace(Regex("[^A-Za-z0-9._-]"), "_")
        sessionDirectory = createUniqueSessionDirectory(
            File(context.filesDir, "recordings"),
            "${timestamp}_${device}_session",
        )
        imuWriter = File(sessionDirectory, "imu_raw.csv").bufferedWriter()
        gnssWriter = File(sessionDirectory, "gnss_raw.csv").bufferedWriter()
        runtimeWriter = File(sessionDirectory, "runtime_10hz.csv").bufferedWriter()
        idrWriter = File(sessionDirectory, "idr_output.csv").bufferedWriter()
        eventWriter = File(sessionDirectory, "events.jsonl").bufferedWriter()
        imuWriter.write("logger_sequence_id,sensor_type,event_timestamp_ns,elapsed_seconds,wall_clock_utc,x,y,z,w,accuracy\n")
        gnssWriter.write("logger_sequence_id,location_timestamp_ns,elapsed_seconds,wall_clock_utc,latitude_deg,longitude_deg,altitude_m,speed_mps,bearing_deg,accuracy_m,vertical_accuracy_m,speed_accuracy_mps,bearing_accuracy_deg,provider,callback_status,masked_from_runtime\n")
        runtimeWriter.write(RUNTIME_HEADER + "\n")
        idrWriter.write(IDR_HEADER + "\n")
        writeMetadata(null, null, null, null)
        logEvent("SESSION_STARTED", "Local recording opened")
    }

    @Synchronized
    fun logSensor(sample: TimedSensorValue, elapsedSeconds: Double, wallClockUtc: String) {
        if (closed) return
        val values = sample.values + List(maxOf(0, 4 - sample.values.size)) { Double.NaN }
        imuWriter.write(
            listOf(
                rawSequence++, sample.kind.csvName, sample.monotonicTimestampNs, format(elapsedSeconds), wallClockUtc,
                nullable(values[0]), nullable(values[1]), nullable(values[2]), nullable(values[3]), sample.accuracy,
            ).joinToString(",") + "\n"
        )
        flushPeriodically()
    }

    @Synchronized
    fun logPhysicalGnss(
        fix: PhysicalGnssFix,
        elapsedSeconds: Double,
        status: GnssStatus,
        maskedFromRuntime: Boolean,
    ) {
        if (closed) return
        gnssWriter.write(
            listOf(
                gnssSequence++, fix.monotonicTimestampNs, format(elapsedSeconds), fix.wallClockUtc,
                format(fix.latitudeDeg), format(fix.longitudeDeg), nullable(fix.altitudeM), nullable(fix.speedMps),
                nullable(fix.bearingDeg), nullable(fix.accuracyM), nullable(fix.verticalAccuracyM),
                nullable(fix.speedAccuracyMps), nullable(fix.bearingAccuracyDeg), csv(fix.provider), status.name,
                maskedFromRuntime,
            ).joinToString(",") + "\n"
        )
        flushPeriodically()
    }

    @Synchronized
    fun logRuntime(sample: LiveIdrSample) {
        if (closed) return
        val g = sample.gnss
        runtimeWriter.write(
            listOf(
                sample.sequenceId, format(sample.elapsedSeconds), sample.monotonicTimestampNs, sample.wallClockUtc,
                nullable(sample.accelerometer?.x), nullable(sample.accelerometer?.y), nullable(sample.accelerometer?.z),
                nullable(sample.gyroscope?.x), nullable(sample.gyroscope?.y), nullable(sample.gyroscope?.z),
                nullable(sample.magnetometer?.x), nullable(sample.magnetometer?.y), nullable(sample.magnetometer?.z),
                nullable(sample.gravity?.x), nullable(sample.gravity?.y), nullable(sample.gravity?.z),
                nullable(sample.rotation?.x), nullable(sample.rotation?.y), nullable(sample.rotation?.z), nullable(sample.rotation?.w),
                nullable(g?.latitudeDeg), nullable(g?.longitudeDeg), nullable(g?.altitudeM), nullable(g?.speedMps), nullable(g?.bearingDeg),
                nullable(g?.accuracyM), nullable(g?.verticalAccuracyM), nullable(g?.speedAccuracyMps), nullable(g?.bearingAccuracyDeg),
                csv(g?.provider), nullable(sample.gnssFixAgeSeconds), sample.gnssIsFresh, sample.gnssStatus.name,
                sample.simulatedBlackout, sample.gnssDiagnostics.blackoutMasksRealFix,
                sample.gnssDiagnostics.physicalCallbackCount,
                nullable(sample.gnssDiagnostics.latestPhysicalCallbackAgeSeconds),
                nullable(sample.gnssDiagnostics.lastPhysicalGnssTimestampNs),
                nullable(sample.gnssDiagnostics.firstValidFixTimestampNs),
                nullable(sample.gnssDiagnostics.timeToFirstFixSeconds),
                sample.gnssDiagnostics.gnssStatusAvailable,
                nullable(sample.gnssDiagnostics.satellitesVisible),
                nullable(sample.gnssDiagnostics.satellitesUsedInFix),
                sample.availability.accelerometer, sample.availability.gyroscope,
                sample.availability.magnetometer, sample.availability.gravity, sample.availability.rotationVector,
                sample.availability.gpsProvider, sample.mlOodState.name, nullable(sample.mlFeatureExceedance),
                nullable(sample.mlCorrectionAccepted),
            ).joinToString(",") + "\n"
        )
        flushPeriodically()
    }

    @Synchronized
    fun logNavigation(sample: LiveIdrSample, state: NavigationState) {
        if (closed) return
        idrWriter.write(
            listOf(
                state.sequenceId,
                format(sample.elapsedSeconds),
                state.monotonicTimestampNs,
                sample.wallClockUtc,
                format(state.eastM),
                format(state.northM),
                nullable(state.latitudeDeg),
                nullable(state.longitudeDeg),
                format(state.speedMps),
                format(state.headingDeg),
                nullable(state.horizontalUncertaintyM),
                state.confidence.name,
                state.localizationMode.name,
                state.alignmentState.name,
                state.motionState.name,
                state.mlState.name,
                nullable(state.mlResidualMps),
                nullable(state.mlOodExceedance),
                format(state.drDurationSeconds),
                nullable(state.gnssInnovationM),
                format(state.lastCorrectionM),
                format(state.engineAverageMs),
                format(state.engineP95Ms),
                sample.gnssStatus.name,
            ).joinToString(",") + "\n"
        )
        flushPeriodically()
    }

    @Synchronized
    fun logEvent(type: String, message: String) {
        if (closed) return
        eventWriter.write("{\"wall_clock_utc\":\"${Instant.now()}\",\"type\":\"${json(type)}\",\"message\":\"${json(message)}\"}\n")
        eventWriter.flush()
    }

    @Synchronized
    fun logFieldTestEvent(type: String, message: String, timestampNs: Long, elapsedSeconds: Double, status: FieldTestStatus) {
        if (closed) return
        eventWriter.write(
            "{\"wall_clock_utc\":\"${Instant.now()}\",\"type\":\"${json(type)}\"," +
                "\"message\":\"${json(message)}\",\"test_id\":${jsonNullable(status.testId)}," +
                "\"preset\":${jsonNullable(status.preset?.name)},\"phase\":\"${status.phase.name}\"," +
                "\"monotonic_timestamp_ns\":$timestampNs,\"elapsed_seconds\":${format(elapsedSeconds)}}\n"
        )
        eventWriter.flush()
    }

    @Synchronized
    fun updateFieldTestStatus(status: FieldTestStatus) {
        fieldTestStatus = status
        if (!closed) writeMetadata(null, null, null, null)
    }

    @Synchronized
    fun close(
        endWallClockMs: Long,
        rates: SensorRateSnapshot,
        gnssDiagnostics: GnssDiagnosticsSnapshot,
        phase11Summary: Phase11SessionSummary? = null,
    ) {
        if (closed) return
        logEvent("SESSION_STOPPED", "Sensor callbacks stopped and files flushed")
        imuWriter.flush(); gnssWriter.flush(); runtimeWriter.flush(); idrWriter.flush(); eventWriter.flush()
        imuWriter.close(); gnssWriter.close(); runtimeWriter.close(); idrWriter.close(); eventWriter.close()
        writeMetadata(endWallClockMs, rates, gnssDiagnostics, phase11Summary)
        closed = true
    }

    private fun writeMetadata(
        endWallClockMs: Long?,
        rates: SensorRateSnapshot?,
        gnssDiagnostics: GnssDiagnosticsSnapshot?,
        phase11Summary: Phase11SessionSummary?,
    ) {
        val sensors = sensorInfo.joinToString(",\n") {
            "    {\"kind\":\"${json(it.kind)}\",\"available\":${it.available},\"name\":${jsonNullable(it.name)}," +
                "\"vendor\":${jsonNullable(it.vendor)},\"resolution\":${it.resolution ?: "null"},\"maximum_range\":${it.maximumRange ?: "null"}}"
        }
        val rateJson = if (rates == null) "null" else """{
    "accelerometer_hz": ${rates.accelerometerHz},
    "gyroscope_hz": ${rates.gyroscopeHz},
    "magnetometer_hz": ${rates.magnetometerHz},
    "gravity_hz": ${rates.gravityHz},
    "rotation_vector_hz": ${rates.rotationVectorHz},
    "normalized_hz": ${rates.normalizedHz}
  }"""
        val gnssJson = if (gnssDiagnostics == null) """{
    "physical_callback_count": 0,
    "last_physical_gnss_timestamp_ns": null,
    "first_valid_fix_timestamp_ns": null,
    "time_to_first_fix_seconds": null,
    "gnss_status_available": false,
    "satellites_visible": null,
    "satellites_used_in_fix": null
  }""" else """{
    "physical_callback_count": ${gnssDiagnostics.physicalCallbackCount},
    "last_physical_gnss_timestamp_ns": ${gnssDiagnostics.lastPhysicalGnssTimestampNs ?: "null"},
    "first_valid_fix_timestamp_ns": ${gnssDiagnostics.firstValidFixTimestampNs ?: "null"},
    "time_to_first_fix_seconds": ${gnssDiagnostics.timeToFirstFixSeconds ?: "null"},
    "gnss_status_available": ${gnssDiagnostics.gnssStatusAvailable},
    "satellites_visible": ${gnssDiagnostics.satellitesVisible ?: "null"},
    "satellites_used_in_fix": ${gnssDiagnostics.satellitesUsedInFix ?: "null"}
  }"""
        val metadata = """{
  "schema_version": 2,
  "session_id": "${json(sessionDirectory.name)}",
  "device_manufacturer": "${json(Build.MANUFACTURER)}",
  "device_model": "${json(Build.MODEL)}",
  "android_version": "${json(Build.VERSION.RELEASE)}",
  "android_sdk": ${Build.VERSION.SDK_INT},
  "app_version": "${json(BuildConfig.VERSION_NAME)}",
  "session_origin_monotonic_ns": $originNs,
  "session_start_utc": "${Instant.ofEpochMilli(startWallClockMs)}",
  "session_end_utc": ${if (endWallClockMs == null) "null" else "\"${Instant.ofEpochMilli(endWallClockMs)}\""},
  "timestamp_semantics": "SensorEvent.timestamp and Location.elapsedRealtimeNanos share Android elapsed-realtime monotonic nanoseconds; elapsed_seconds is relative to session origin; wall UTC is diagnostic only.",
  "device_frame": "Android sensor frame: +X right, +Y toward phone top, +Z out of screen; no vehicle-forward claim.",
  "units": {"accelerometer":"m/s^2","gyroscope":"rad/s","magnetometer":"microtesla","speed":"m/s","angles":"degrees","position":"WGS84 latitude/longitude degrees"},
  "requested_sampling_period_us": $requestedSamplingPeriodUs,
  "normalized_target_hz": $normalizedRateHz,
  "phase10_idr_output_schema_version": 1,
  "phase11_engine_version": "11.0",
  "location_provider": "${json(locationProvider)}",
  "storage": "app-private local files; no upload or analytics",
  "availability": {"accelerometer":${availability.accelerometer},"gyroscope":${availability.gyroscope},"magnetometer":${availability.magnetometer},"gravity":${availability.gravity},"rotation_vector":${availability.rotationVector},"gps_provider":${availability.gpsProvider}},
  "sensors": [
$sensors
  ],
  "observed_rates": $rateJson,
  "gnss_diagnostics": $gnssJson,
  "phase11_gnss_semantics": {
    "legacy_blackout_masks_real_fix_meaning": "simulated blackout active and a valid physical fix was acquired at any earlier time in this session",
    "physical_fix_state": "${gnssDiagnostics?.physicalFixState?.name ?: "NONE"}",
    "runtime_gnss_availability": "${gnssDiagnostics?.runtimeGnssAvailability?.name ?: "UNAVAILABLE"}",
    "real_fix_acquired_this_session": ${gnssDiagnostics?.hasAcquiredRealFixThisSession ?: false},
    "blackout_masks_fresh_fix": ${gnssDiagnostics?.blackoutMasksFreshFix ?: false}
  },
  "field_test": ${fieldTestJson(fieldTestStatus)},
  "phase11_runtime_summary": ${phase11SummaryJson(phase11Summary)}
}
"""
        File(sessionDirectory, "session_metadata.json").writeText(metadata)
    }

    private fun flushPeriodically() {
        pendingWrites += 1
        if (pendingWrites >= 100) {
            imuWriter.flush(); gnssWriter.flush(); runtimeWriter.flush(); idrWriter.flush()
            pendingWrites = 0
        }
    }

    private fun nullable(value: Any?): String = when (value) {
        null -> ""
        is Double -> if (value.isFinite()) format(value) else ""
        is Float -> if (value.isFinite()) format(value.toDouble()) else ""
        else -> value.toString()
    }

    private fun format(value: Double): String = "%.9f".format(java.util.Locale.US, value)
    private fun csv(value: String?): String = if (value == null) "" else "\"${value.replace("\"", "\"\"")}\""
    private fun json(value: String): String = value.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n")
    private fun jsonNullable(value: String?): String = if (value == null) "null" else "\"${json(value)}\""

    private fun fieldTestJson(status: FieldTestStatus): String = """{
    "test_id": ${jsonNullable(status.testId)},
    "preset": ${jsonNullable(status.preset?.name)},
    "blackout_duration_seconds": ${status.preset?.blackoutDurationSeconds ?: "null"},
    "mount_profile": "${status.mountProfile.name}",
    "final_phase": "${status.phase.name}"
  }"""

    private fun phase11SummaryJson(summary: Phase11SessionSummary?): String {
        val start = summary?.startSystemHealth ?: initialSystemHealth
        val end = summary?.endSystemHealth
        val mlCounts = summary?.mlStateCounts?.entries?.sortedBy { it.key }?.joinToString(",") {
            "\"${json(it.key)}\":${it.value}"
        } ?: ""
        return """{
    "runtime_sample_count": ${summary?.runtimeSampleCount ?: 0},
    "engine_average_ms": ${summary?.engineAverageMs ?: "null"},
    "engine_p95_ms": ${summary?.engineP95Ms ?: "null"},
    "final_localization_state": ${jsonNullable(summary?.finalLocalizationState)},
    "final_alignment_state": ${jsonNullable(summary?.finalAlignmentState)},
    "final_motion_state": ${jsonNullable(summary?.finalMotionState)},
    "ml_state_counts": {$mlCounts},
    "logger_error_count": ${end?.loggerErrorCount ?: start.loggerErrorCount},
    "foreground_service_active_at_close": ${end?.foregroundServiceActive ?: false},
    "battery_start_percent": ${start.batteryPercent ?: "null"},
    "battery_end_percent": ${end?.batteryPercent ?: "null"},
    "battery_temperature_start_c": ${start.batteryTemperatureC ?: "null"},
    "battery_temperature_end_c": ${end?.batteryTemperatureC ?: "null"},
    "thermal_status_start": ${jsonNullable(start.thermalStatus)},
    "thermal_status_end": ${jsonNullable(end?.thermalStatus)},
    "battery_percentage_note": "Observability only; percentage change is not a calibrated energy measurement."
  }"""
    }

    companion object {
        const val RUNTIME_HEADER = "sequence_id,elapsed_seconds,monotonic_timestamp_ns,wall_clock_utc," +
            "accelerometer_x_mps2,accelerometer_y_mps2,accelerometer_z_mps2," +
            "gyroscope_x_radps,gyroscope_y_radps,gyroscope_z_radps," +
            "magnetometer_x_ut,magnetometer_y_ut,magnetometer_z_ut," +
            "gravity_x_mps2,gravity_y_mps2,gravity_z_mps2," +
            "rotation_qx,rotation_qy,rotation_qz,rotation_qw," +
            "gnss_latitude_deg,gnss_longitude_deg,gnss_altitude_m,gnss_speed_mps,gnss_bearing_deg," +
            "gnss_accuracy_m,gnss_vertical_accuracy_m,gnss_speed_accuracy_mps,gnss_bearing_accuracy_deg,gnss_provider," +
            "gnss_fix_age_seconds,gnss_is_fresh,gnss_status,simulated_blackout,blackout_masks_real_fix," +
            "physical_gnss_callback_count,latest_physical_callback_age_seconds,last_physical_gnss_timestamp_ns," +
            "first_valid_gnss_fix_timestamp_ns,time_to_first_fix_seconds,gnss_status_available," +
            "satellites_visible,satellites_used_in_fix," +
            "accelerometer_available,gyroscope_available,magnetometer_available,gravity_available,rotation_vector_available,gps_provider_available," +
            "ml_ood_state,ml_feature_exceedance,ml_correction_accepted"
        const val IDR_HEADER = "sequence_id,elapsed_seconds,monotonic_timestamp_ns,wall_clock_utc," +
            "local_east_m,local_north_m,estimated_latitude_deg,estimated_longitude_deg," +
            "estimated_speed_mps,estimated_heading_deg,horizontal_uncertainty_m,confidence," +
            "localization_state,alignment_state,motion_state,ml_state,ml_residual_mps,ml_ood_exceedance," +
            "dr_duration_seconds,gnss_innovation_m,last_correction_m,engine_average_ms,engine_p95_ms,gnss_acquisition_state"
    }
}

internal fun createUniqueSessionDirectory(recordingsRoot: File, baseName: String): File {
    check(recordingsRoot.mkdirs() || recordingsRoot.isDirectory) { "Cannot create recordings directory." }
    var suffix = 0
    while (true) {
        val name = if (suffix == 0) baseName else "${baseName}_$suffix"
        val candidate = File(recordingsRoot, name)
        if (candidate.mkdir()) return candidate
        check(candidate.exists()) { "Cannot create session directory." }
        suffix += 1
    }
}

fun Sensor.toDeviceSensorInfo(kind: String) = DeviceSensorInfo(
    kind = kind,
    available = true,
    name = name,
    vendor = vendor,
    resolution = resolution,
    maximumRange = maximumRange,
)
