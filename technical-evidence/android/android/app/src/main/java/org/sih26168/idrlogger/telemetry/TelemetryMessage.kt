package org.sih26168.idrlogger.telemetry

import java.time.Instant
import org.sih26168.idrlogger.engine.NavigationState
import org.sih26168.idrlogger.engine.MlRuntimeState
import org.sih26168.idrlogger.model.FieldTestPhase
import org.sih26168.idrlogger.model.GnssDiagnosticsSnapshot
import org.sih26168.idrlogger.model.GnssStatus
import org.sih26168.idrlogger.model.SensorRateSnapshot
import org.sih26168.idrlogger.model.SystemHealthSnapshot

enum class TelemetryMapMode { LOCAL_ENU, GOOGLE_MAPS }

/** Allowlisted diagnostics: no LoggerStatus, raw sample, raw fix, path, or arbitrary message. */
data class TelemetryDiagnostics(
    val wallTimeUtc: String? = null,
    val gnssStatus: GnssStatus = GnssStatus.WAITING_FOR_FIRST_FIX,
    val gnss: GnssDiagnosticsSnapshot = GnssDiagnosticsSnapshot(),
    val rates: SensorRateSnapshot? = null,
    val health: SystemHealthSnapshot = SystemHealthSnapshot(),
    val fieldTestPhase: FieldTestPhase = FieldTestPhase.IDLE,
    val mapMode: TelemetryMapMode = TelemetryMapMode.LOCAL_ENU,
    val recording: Boolean = false,
)

/**
 * Only completed engine state crosses this boundary. Physical GNSS/reference objects cannot enter.
 * Private construction and a fixed field allowlist protect blackout/reference isolation.
 */
class TelemetryMessage private constructor(
    internal val timestampNs: Long,
    internal val fields: Map<String, Any?>,
) {
    companion object {
        fun fromNavigation(state: NavigationState, diagnostics: TelemetryDiagnostics): TelemetryMessage {
            fun finite(value: Double?) = value?.takeIf { it.isFinite() }
            fun nonnegative(value: Double?) = finite(value)?.takeIf { it in 0.0..1e9 }
            val gnss = diagnostics.gnss
            val rates = diagnostics.rates
            val health = diagnostics.health
            val lat = finite(state.latitudeDeg)?.takeIf { it in -90.0..90.0 }
            val lon = finite(state.longitudeDeg)?.takeIf { it in -180.0..180.0 }
            val hasPosition = lat != null && lon != null
            val east = finite(state.eastM)?.takeIf { it in -1e8..1e8 }
            val north = finite(state.northM)?.takeIf { it in -1e8..1e8 }
            val hasLocal = hasPosition && east != null && north != null
            val speed = if (hasPosition) nonnegative(state.speedMps)?.takeIf { it <= 1000 } else null
            val aiState = when (state.mlState) {
                MlRuntimeState.ML_WARMING -> "WARMING"
                MlRuntimeState.ML_ACCEPTED -> "ASSISTED"
                MlRuntimeState.ML_OOD_LIMITED, MlRuntimeState.ML_REJECTED -> "SAFETY_FALLBACK"
                MlRuntimeState.ML_UNAVAILABLE -> "UNAVAILABLE"
            }
            val wallUtc = diagnostics.wallTimeUtc?.let {
                try { Instant.parse(it).toString() } catch (_: Exception) { null }
            }
            val thermal = health.thermalStatus?.takeIf {
                it in setOf("NONE", "LIGHT", "MODERATE", "SEVERE", "CRITICAL", "EMERGENCY", "SHUTDOWN")
            }
            return TelemetryMessage(state.monotonicTimestampNs.coerceAtLeast(0L), linkedMapOf(
                "wall_time_utc" to wallUtc, "mode" to "LIVE",
                "estimated_position" to linkedMapOf(
                    "latitude" to if (hasPosition) lat else null,
                    "longitude" to if (hasPosition) lon else null,
                    "local_east_m" to if (hasLocal) east else null,
                    "local_north_m" to if (hasLocal) north else null,
                ),
                "motion" to linkedMapOf(
                    "speed_mps" to speed, "speed_kmh" to finite(speed?.times(3.6)),
                    "heading_deg" to if (hasPosition) finite(state.headingDeg)?.let { (it % 360.0 + 360.0) % 360.0 } else null,
                ),
                "navigation" to linkedMapOf(
                    "localization_state" to state.localizationMode.name,
                    "gnss_state" to diagnostics.gnssStatus.name,
                    "dr_duration_s" to nonnegative(state.drDurationSeconds),
                    "uncertainty_m" to nonnegative(state.horizontalUncertaintyM),
                    "confidence" to state.confidence.name, "alignment_state" to state.alignmentState.name,
                    "motion_state" to state.motionState.name,
                ),
                "ai" to linkedMapOf("state" to aiState, "ml_state" to state.mlState.name,
                    "ood_exceedance" to nonnegative(state.mlOodExceedance)),
                "sensors" to linkedMapOf(
                    "accelerometer_hz" to nonnegative(rates?.accelerometerHz)?.takeIf { it <= 10000 },
                    "gyroscope_hz" to nonnegative(rates?.gyroscopeHz)?.takeIf { it <= 10000 },
                    "magnetometer_hz" to nonnegative(rates?.magnetometerHz)?.takeIf { it <= 10000 },
                    "runtime_hz" to nonnegative(rates?.normalizedHz)?.takeIf { it <= 10000 },
                ),
                "gnss_observability" to linkedMapOf(
                    "satellites_visible" to gnss.satellitesVisible?.takeIf { gnss.gnssStatusAvailable && it in 0..1000 },
                    "satellites_used" to gnss.satellitesUsedInFix?.takeIf { gnss.gnssStatusAvailable && it in 0..1000 },
                    "status_available" to gnss.gnssStatusAvailable,
                    "physical_callback_count" to gnss.physicalCallbackCount.coerceAtLeast(0),
                    "latest_callback_age_s" to nonnegative(gnss.latestPhysicalCallbackAgeSeconds),
                    "blackout_masks_real_fix" to gnss.blackoutMasksFreshFix,
                ),
                "engine" to linkedMapOf("avg_ms" to nonnegative(state.engineAverageMs),
                    "p95_ms" to nonnegative(state.engineP95Ms)),
                "device" to linkedMapOf(
                    "battery_percent" to finite(health.batteryPercent)?.takeIf { it in 0.0..100.0 }?.toInt(),
                    "battery_temperature_c" to finite(health.batteryTemperatureC)?.takeIf { it in -100.0..200.0 }, "thermal_state" to thermal,
                ),
                "field_test_state" to diagnostics.fieldTestPhase.name,
                "map_mode" to diagnostics.mapMode.name, "recording" to diagnostics.recording,
            ))
        }
    }
}
