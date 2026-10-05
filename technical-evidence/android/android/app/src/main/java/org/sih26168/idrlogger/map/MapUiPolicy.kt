package org.sih26168.idrlogger.map

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin
import org.sih26168.idrlogger.engine.LocalizationMode
import org.sih26168.idrlogger.engine.MotionState

data class GeographicPoint(val latitudeDeg: Double, val longitudeDeg: Double)

object MapCoordinateProjector {
    private const val EARTH_RADIUS_M = 6_371_008.8

    fun fromCurrentEnginePosition(
        pointEastM: Double,
        pointNorthM: Double,
        currentEastM: Double,
        currentNorthM: Double,
        currentLatitudeDeg: Double,
        currentLongitudeDeg: Double,
    ): GeographicPoint {
        val latitude = currentLatitudeDeg + (pointNorthM - currentNorthM) / EARTH_RADIUS_M * 180.0 / PI
        val longitudeScale = (EARTH_RADIUS_M * cos(currentLatitudeDeg * PI / 180.0)).coerceAtLeast(1.0)
        val longitude = currentLongitudeDeg + (pointEastM - currentEastM) / longitudeScale * 180.0 / PI
        return GeographicPoint(latitude, wrapLongitude(longitude))
    }

    private fun wrapLongitude(value: Double): Double {
        var wrapped = (value + 180.0) % 360.0
        if (wrapped < 0.0) wrapped += 360.0
        return wrapped - 180.0
    }
}

class MapCameraPolicy(
    private val minimumUpdateIntervalMs: Long = 250L,
    headingUp: Boolean = true,
) {
    var headingUp: Boolean = headingUp
        private set
    var following: Boolean = true
        private set
    private var lastUpdateMs: Long = Long.MIN_VALUE
    private var smoothedBearingDeg: Double = 0.0
    private var frameBearingInitialized = false
    private var bearingTracking = false
    private var previousFrame: MapCameraFrame? = null

    fun onUserGesture() { following = false }
    fun recenter() {
        following = true
        headingUp = true
        lastUpdateMs = Long.MIN_VALUE
        previousFrame = null
    }

    fun shouldUpdate(nowMs: Long): Boolean {
        if (!following) return false
        if (lastUpdateMs != Long.MIN_VALUE && nowMs - lastUpdateMs < minimumUpdateIntervalMs) return false
        lastUpdateMs = nowMs
        return true
    }

    fun bearing(headingDeg: Double, speedMps: Double = 10.0, motionState: MotionState = MotionState.MOVING, headingReliable: Boolean = true): Float {
        if (!headingUp) return 0f
        if (!headingReliable || !headingDeg.isFinite() || !speedMps.isFinite() || speedMps < 1.0 || motionState != MotionState.MOVING) {
            bearingTracking = false
            return smoothedBearingDeg.toFloat()
        }
        if (!bearingTracking && speedMps < MINIMUM_BEARING_SPEED_MPS) return smoothedBearingDeg.toFloat()
        bearingTracking = true
        var delta = ((normalizeBearing(headingDeg) - smoothedBearingDeg + 540.0) % 360.0) - 180.0
        if (kotlin.math.abs(delta) < 1.0) return smoothedBearingDeg.toFloat()
        delta = delta.coerceIn(-18.0, 18.0)
        smoothedBearingDeg = (smoothedBearingDeg + delta * 0.35 + 360.0) % 360.0
        return smoothedBearingDeg.toFloat()
    }

    /** Camera-only framing. Never write this target back into a marker, snapshot, log or telemetry. */
    fun frame(marker: EngineMarker, speedMps: Double, motionState: MotionState, mode: LocalizationMode, headingReliable: Boolean = true): MapCameraFrame? {
        val latitude = marker.latitudeDeg ?: return null
        val longitude = marker.longitudeDeg ?: return null
        if (!latitude.isFinite() || !longitude.isFinite() || latitude !in -90.0..90.0 || longitude !in -180.0..180.0) return null
        val active = mode in ACTIVE_MODES
        val speed = if (speedMps.isFinite()) speedMps.coerceAtLeast(0.0) else 0.0
        if (!frameBearingInitialized && headingUp && headingReliable && marker.headingDeg.isFinite() &&
            speed >= MINIMUM_BEARING_SPEED_MPS && motionState == MotionState.MOVING) {
            smoothedBearingDeg = normalizeBearing(marker.headingDeg)
            frameBearingInitialized = true
        }
        val bearing = bearing(marker.headingDeg, speed, motionState, headingReliable)
        val desiredLookAhead = if (headingUp && active && frameBearingInitialized && motionState == MotionState.MOVING && speed >= 1.0)
            (10.0 + speed * 3.2).coerceAtMost(MAXIMUM_LOOK_AHEAD_M) else 0.0
        val previous = previousFrame
        val lookAhead = previous?.let { it.lookAheadM + (desiredLookAhead - it.lookAheadM) * 0.2 } ?: desiredLookAhead
        val radians = bearing * PI / 180.0
        val desiredTarget = MapCoordinateProjector.fromCurrentEnginePosition(
            lookAhead * sin(radians), lookAhead * cos(radians), 0.0, 0.0, latitude, longitude,
        )
        // Target lag is visual only. Interpolate longitude on the short arc at the dateline.
        val target = previous?.target?.let {
            val separationM = Google3dCameraCommandGate.distanceM(
                it.latitudeDeg,
                it.longitudeDeg,
                desiredTarget.latitudeDeg,
                desiredTarget.longitudeDeg,
            )
            val followFraction = when {
                separationM >= 35.0 -> 1.0
                separationM >= 8.0 -> 0.86
                separationM >= 1.0 -> 0.72
                else -> 0.45
            }
            val deltaLon = ((desiredTarget.longitudeDeg - it.longitudeDeg + 540.0) % 360.0) - 180.0
            GeographicPoint(it.latitudeDeg + (desiredTarget.latitudeDeg - it.latitudeDeg) * followFraction,
                ((it.longitudeDeg + deltaLon * followFraction + 540.0) % 360.0) - 180.0)
        } ?: desiredTarget
        val desiredTilt = if (headingUp && active) (59.0 + speed * 0.2).coerceAtMost(66.0).toFloat() else 0f
        val desiredZoom = if (active) (18.8 - speed * 0.035).coerceIn(17.4, 18.8).toFloat() else 17.8f
        return MapCameraFrame(
            target = target,
            bearingDeg = bearing,
            tiltDeg = previous?.let { it.tiltDeg + (desiredTilt - it.tiltDeg) * 0.2f } ?: desiredTilt,
            zoom = previous?.let { it.zoom + (desiredZoom - it.zoom) * 0.12f } ?: desiredZoom,
            lookAheadM = lookAhead,
        ).also { previousFrame = it }
    }

    companion object {
        const val MINIMUM_BEARING_SPEED_MPS = 2.0
        const val MAXIMUM_LOOK_AHEAD_M = 120.0
        private val ACTIVE_MODES = setOf(LocalizationMode.GNSS_ACTIVE, LocalizationMode.GNSS_DEGRADED,
            LocalizationMode.IDR_ACTIVE, LocalizationMode.GNSS_VERIFYING, LocalizationMode.GNSS_RECOVERING)
        fun normalizeBearing(value: Double): Double = ((value % 360.0) + 360.0) % 360.0
    }
}

data class MapCameraFrame(
    val target: GeographicPoint,
    val bearingDeg: Float,
    val tiltDeg: Float,
    val zoom: Float,
    val lookAheadM: Double,
)

/** Pure shared palette: ordinary GNSS denial is amber, never an error. */
object MapStateStyle {
    fun color(mode: LocalizationMode): Int = when (mode) {
        LocalizationMode.GNSS_ACTIVE -> 0xFF4AD8B5.toInt()
        LocalizationMode.GNSS_DEGRADED, LocalizationMode.IDR_ACTIVE -> 0xFFFFAE48.toInt()
        LocalizationMode.GNSS_VERIFYING, LocalizationMode.GNSS_RECOVERING -> 0xFF967EFF.toInt()
        LocalizationMode.ERROR -> 0xFFFF5C69.toInt()
        else -> 0xFF7D93A5.toInt()
    }
    fun pathWidth(mode: LocalizationMode): Float = if (mode == LocalizationMode.IDR_ACTIVE) 8f else 6f
}

/** onMapReady only supplies a canvas. Only an actual completed tile load marks it useful. */
class MapLoadPolicy(private val timeoutMs: Long = 12_000L) {
    var loading: Boolean = false
        private set
    var loaded: Boolean = false
        private set
    private var startedMs: Long = 0L

    fun begin(nowMs: Long) { startedMs = nowMs; loading = true; loaded = false }
    fun timedOut(nowMs: Long): Boolean = loading && nowMs - startedMs >= timeoutMs
    fun onTilesLoaded(nowMs: Long): Boolean {
        if (!loading || timedOut(nowMs)) { if (timedOut(nowMs)) fail(); return false }
        loading = false; loaded = true
        return true
    }
    fun fail() { loading = false; loaded = false }
}
