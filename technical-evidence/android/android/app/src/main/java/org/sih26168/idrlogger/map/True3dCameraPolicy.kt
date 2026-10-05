package org.sih26168.idrlogger.map

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.sin
import org.sih26168.idrlogger.engine.LocalizationMode
import org.sih26168.idrlogger.engine.MotionState

/**
 * Presentation-only chase camera for the MapLibre renderer.
 * It consumes an immutable engine marker and never feeds coordinates back to localization.
 */
class True3dCameraPolicy(
    private val minimumUpdateIntervalMs: Long = 80L,
) {
    var following: Boolean = true
        private set
    private var lastUpdateMs = Long.MIN_VALUE
    private var initialized = false
    private var bearingDeg = 0.0
    private var pitchDeg = 60.0
    private var zoom = 16.85
    private var lookAheadM = 0.0
    private var target: GeographicPoint? = null

    fun onUserGesture() { following = false }

    fun recenter() {
        following = true
        lastUpdateMs = Long.MIN_VALUE
        target = null
    }

    fun shouldUpdate(nowMs: Long): Boolean {
        if (!following) return false
        if (lastUpdateMs != Long.MIN_VALUE && nowMs - lastUpdateMs < minimumUpdateIntervalMs) return false
        lastUpdateMs = nowMs
        return true
    }

    fun frame(
        marker: EngineMarker,
        speedMps: Double,
        motionState: MotionState,
        mode: LocalizationMode,
        headingReliable: Boolean,
    ): True3dCameraFrame? {
        val latitude = marker.latitudeDeg ?: return null
        val longitude = marker.longitudeDeg ?: return null
        if (!latitude.isFinite() || !longitude.isFinite() || latitude !in -90.0..90.0 || longitude !in -180.0..180.0) return null
        val speed = speedMps.takeIf(Double::isFinite)?.coerceAtLeast(0.0) ?: 0.0
        val moving = motionState == MotionState.MOVING
        val canTrackBearing = headingReliable && marker.headingDeg.isFinite() && moving && speed >= 2.0
        if (!initialized) {
            if (canTrackBearing) bearingDeg = normalize(marker.headingDeg)
            initialized = true
        } else if (canTrackBearing) {
            val delta = shortestDelta(bearingDeg, normalize(marker.headingDeg)).coerceIn(-16.0, 16.0)
            if (abs(delta) >= 0.35) bearingDeg = normalize(bearingDeg + delta * 0.32)
        }

        val desiredLookAhead = if (moving && mode in ACTIVE_MODES) when {
            speed < 1.0 -> 0.0
            speed < 5.0 -> 5.0 + speed * 2.0
            speed < 15.0 -> 15.0 + (speed - 5.0) * 2.5
            speed < 40.0 -> 40.0 + (speed - 15.0) * 1.4
            speed < 75.0 -> 75.0 + (speed - 40.0) * (45.0 / 35.0)
            else -> 120.0
        } else 0.0
        // A stopped user must be framed at the actual engine marker immediately.  Easing the
        // previous chase look-ahead toward zero left the camera visually parked several metres
        // ahead after a vehicle stopped, which looked like a wrong location in Google 3D.
        lookAheadM = if (!moving || speed < 1.0) {
            0.0
        } else if (target == null) {
            desiredLookAhead
        } else {
            lookAheadM + (desiredLookAhead - lookAheadM) * 0.22
        }

        // Preserve useful road context at walking/stationary speed.  The former 18.25 zoom
        // framed only a few buildings and made an accurate marker look lost under the HUD.
        val desiredPitch = if (mode in ACTIVE_MODES) (60.0 + (speed / 18.0).coerceIn(0.0, 5.0)) else 56.0
        val desiredZoom = (17.15 - speed * 0.035).coerceIn(15.95, 17.15)
        pitchDeg += (desiredPitch - pitchDeg) * 0.18
        zoom += (desiredZoom - zoom) * 0.14

        val radians = bearingDeg * PI / 180.0
        val desiredTarget = MapCoordinateProjector.fromCurrentEnginePosition(
            lookAheadM * sin(radians), lookAheadM * cos(radians), 0.0, 0.0, latitude, longitude,
        )
        val smoothedTarget = if (!moving || speed < 1.0) {
            desiredTarget
        } else target?.let {
            val separationM = Google3dCameraCommandGate.distanceM(
                it.latitudeDeg,
                it.longitudeDeg,
                desiredTarget.latitudeDeg,
                desiredTarget.longitudeDeg,
            )
            // Rendering-only follow policy. Never make a newly acquired/current engine position
            // crawl in from an old camera target: large errors snap, ordinary motion catches up
            // quickly, and sub-metre GNSS noise remains visually damped.
            val followFraction = when {
                separationM >= LARGE_CATCH_UP_M -> 1.0
                separationM >= MEDIUM_CATCH_UP_M -> 0.86
                separationM >= SMALL_CATCH_UP_M -> 0.72
                else -> 0.45
            }
            val deltaLon = shortestDelta(it.longitudeDeg, desiredTarget.longitudeDeg)
            GeographicPoint(
                it.latitudeDeg + (desiredTarget.latitudeDeg - it.latitudeDeg) * followFraction,
                wrapLongitude(it.longitudeDeg + deltaLon * followFraction),
            )
        } ?: desiredTarget
        target = smoothedTarget
        return True3dCameraFrame(smoothedTarget, bearingDeg, pitchDeg.coerceIn(56.0, 66.0), zoom, lookAheadM)
    }

    companion object {
        private val ACTIVE_MODES = setOf(
            LocalizationMode.GNSS_ACTIVE, LocalizationMode.GNSS_DEGRADED, LocalizationMode.IDR_ACTIVE,
            LocalizationMode.GNSS_VERIFYING, LocalizationMode.GNSS_RECOVERING,
        )
        private const val SMALL_CATCH_UP_M = 1.0
        private const val MEDIUM_CATCH_UP_M = 8.0
        private const val LARGE_CATCH_UP_M = 35.0
        private fun normalize(value: Double): Double = ((value % 360.0) + 360.0) % 360.0
        private fun shortestDelta(from: Double, to: Double): Double = ((to - from + 540.0) % 360.0) - 180.0
        private fun wrapLongitude(value: Double): Double = ((value + 540.0) % 360.0) - 180.0
    }
}

data class True3dCameraFrame(
    val target: GeographicPoint,
    val bearingDeg: Double,
    val pitchDeg: Double,
    val zoom: Double,
    val lookAheadM: Double,
)
