package org.sih26168.idrlogger.map

import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.hypot
import org.sih26168.idrlogger.engine.LocalizationMode
import org.sih26168.idrlogger.engine.TrajectoryPoint

/** Single-slot mailbox: producers can never build a visual-render FIFO backlog. */
class LatestValueSlot<T : Any> {
    private var pending: T? = null
    var offeredCount: Long = 0L
        private set
    var supersededCount: Long = 0L
        private set

    fun offer(value: T) {
        offeredCount += 1
        if (pending != null) supersededCount += 1
        pending = value
    }

    fun takeLatest(): T? = pending.also { pending = null }
    fun hasValue(): Boolean = pending != null
    fun clear() { pending = null }
}

/** Distinguishes an intentional map pan from the small MOVE events emitted by taps/hand jitter. */
class FollowGestureGate(private val touchSlopPx: Float) {
    private var downX = 0f
    private var downY = 0f
    private var tracking = false
    private var paused = false

    init { require(touchSlopPx >= 0f) }

    fun onDown(x: Float, y: Float) {
        downX = x
        downY = y
        tracking = true
        paused = false
    }

    /** Returns true exactly once when movement becomes a deliberate drag. */
    fun onMove(x: Float, y: Float): Boolean {
        if (!tracking || paused) return false
        if (hypot((x - downX).toDouble(), (y - downY).toDouble()) < touchSlopPx) return false
        paused = true
        return true
    }

    /** A second finger is always an intentional map gesture (pinch, tilt, or rotate). */
    fun onAdditionalPointer(): Boolean {
        if (!tracking || paused) return false
        paused = true
        return true
    }

    fun onEnd() { tracking = false }
}

/** Invalidates delayed camera-follow work as soon as the user takes control of the map. */
class FollowResumeGuard {
    private var generation = 0L

    fun token(): Long = generation
    fun invalidate() { generation += 1L }
    fun isCurrent(token: Long): Boolean = token == generation
}

data class Google3dCameraVisualState(
    val latitudeDeg: Double,
    val longitudeDeg: Double,
    val bearingDeg: Double,
    val pitchDeg: Double,
    val rangeM: Double,
)

enum class CameraSanityAction { NONE, RETRY, FAIL }

/** Rejects a Maps 3D camera that silently remains at a world-scale/default location. */
class Google3dCameraSanityGate(
    private val maximumCenterErrorM: Double = 2_000.0,
    private val minimumMaximumRangeM: Double = 3_000.0,
    private val rangeMultiplier: Double = 8.0,
) {
    private var consecutiveFailures = 0

    fun observe(
        expected: Google3dCameraVisualState?,
        actual: Google3dCameraVisualState?,
        following: Boolean,
    ): CameraSanityAction {
        if (!following || expected == null) {
            consecutiveFailures = 0
            return CameraSanityAction.NONE
        }
        val invalid = actual == null || listOf(
            actual.latitudeDeg, actual.longitudeDeg, actual.bearingDeg, actual.pitchDeg, actual.rangeM,
        ).any { !it.isFinite() } || actual.latitudeDeg !in -90.0..90.0 || actual.longitudeDeg !in -180.0..180.0 ||
            Google3dCameraCommandGate.distanceM(
                expected.latitudeDeg,
                expected.longitudeDeg,
                actual.latitudeDeg,
                actual.longitudeDeg,
            ) > maximumCenterErrorM ||
            actual.rangeM > maxOf(minimumMaximumRangeM, expected.rangeM * rangeMultiplier)
        if (!invalid) {
            consecutiveFailures = 0
            return CameraSanityAction.NONE
        }
        consecutiveFailures += 1
        return if (consecutiveFailures >= 2) CameraSanityAction.FAIL else CameraSanityAction.RETRY
    }

    fun reset() { consecutiveFailures = 0 }
}

/** Debounces transient mobile-network validation changes before replacing an online renderer. */
class RendererNetworkGate(private val failuresBeforeFallback: Int = 2) {
    private var failures = 0

    init { require(failuresBeforeFallback > 0) }

    fun shouldFallback(validatedInternet: Boolean): Boolean {
        if (validatedInternet) {
            failures = 0
            return false
        }
        failures += 1
        return failures >= failuresBeforeFallback
    }

    fun reset() { failures = 0 }
}

/** Prevents native camera command queues while keeping the newest pose visually current. */
class Google3dCameraCommandGate(
    private val minimumIntervalMs: Long = 125L,
    private val maximumSilenceMs: Long = 750L,
    private val minimumPositionChangeM: Double = 0.45,
    private val minimumBearingChangeDeg: Double = 2.0,
    private val minimumPitchChangeDeg: Double = 0.8,
    private val minimumRangeChangeM: Double = 3.0,
) {
    private var lastCommandMs = Long.MIN_VALUE
    private var lastState: Google3dCameraVisualState? = null

    fun shouldIssue(nowMs: Long, state: Google3dCameraVisualState, force: Boolean = false): Boolean {
        val previous = lastState
        if (!force && lastCommandMs != Long.MIN_VALUE && nowMs - lastCommandMs < minimumIntervalMs) return false
        val meaningful = previous == null ||
            distanceM(previous.latitudeDeg, previous.longitudeDeg, state.latitudeDeg, state.longitudeDeg) >= minimumPositionChangeM ||
            angularDistance(previous.bearingDeg, state.bearingDeg) >= minimumBearingChangeDeg ||
            abs(previous.pitchDeg - state.pitchDeg) >= minimumPitchChangeDeg ||
            abs(previous.rangeM - state.rangeM) >= minimumRangeChangeM ||
            (lastCommandMs != Long.MIN_VALUE && nowMs - lastCommandMs >= maximumSilenceMs)
        if (!force && !meaningful) return false
        lastCommandMs = nowMs
        lastState = state
        return true
    }

    fun reset() {
        lastCommandMs = Long.MIN_VALUE
        lastState = null
    }

    companion object {
        internal fun distanceM(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
            val north = (lat2 - lat1) * 111_132.0
            val east = (lon2 - lon1) * 111_320.0 * cos(Math.toRadians((lat1 + lat2) * 0.5))
            return hypot(east, north)
        }

        internal fun angularDistance(first: Double, second: Double): Double =
            abs(((second - first + 540.0) % 360.0) - 180.0)
    }
}

/** Bounded presentation trail; the full engine trajectory and logs remain unchanged. */
object Google3dVisualTrajectory {
    const val MAXIMUM_POINTS = 320
    private const val MINIMUM_SPACING_M = 1.5

    fun decimate(points: List<TrajectoryPoint>): List<TrajectoryPoint> {
        if (points.size <= 2) return points
        val stride = ((points.size + MAXIMUM_POINTS - 1) / MAXIMUM_POINTS).coerceAtLeast(1)
        val output = ArrayList<TrajectoryPoint>(minOf(points.size, MAXIMUM_POINTS))
        output += points.first()
        var previous = points.first()
        for (index in 1 until points.lastIndex) {
            val point = points[index]
            val modeChanged = point.localizationMode != previous.localizationMode
            if ((index % stride == 0 || modeChanged) &&
                (modeChanged || hypot(point.eastM - previous.eastM, point.northM - previous.northM) >= MINIMUM_SPACING_M)
            ) {
                output += point
                previous = point
                if (output.size >= MAXIMUM_POINTS - 1) break
            }
        }
        if (output.last() != points.last()) output += points.last()
        return output
    }
}

/** Independent clocks for expensive overlays. */
class Google3dOverlayGate(
    private val trajectoryIntervalMs: Long = 1_000L,
    private val uncertaintyIntervalMs: Long = 750L,
    private val uncertaintyMaximumSilenceMs: Long = 2_000L,
) {
    private var lastTrajectoryMs = Long.MIN_VALUE
    private var lastTrajectorySignature = Long.MIN_VALUE
    private var lastUncertaintyMs = Long.MIN_VALUE
    private var lastUncertaintyLat: Double? = null
    private var lastUncertaintyLon: Double? = null
    private var lastUncertaintyRadius: Double? = null
    private var lastUncertaintyMode: LocalizationMode? = null

    fun shouldUpdateTrajectory(nowMs: Long, signature: Long, force: Boolean = false): Boolean {
        if (!force && signature == lastTrajectorySignature) return false
        if (!force && lastTrajectoryMs != Long.MIN_VALUE && nowMs - lastTrajectoryMs < trajectoryIntervalMs) return false
        lastTrajectoryMs = nowMs
        lastTrajectorySignature = signature
        return true
    }

    fun shouldUpdateUncertainty(
        nowMs: Long,
        latitudeDeg: Double,
        longitudeDeg: Double,
        radiusM: Double?,
        mode: LocalizationMode,
        force: Boolean = false,
    ): Boolean {
        val elapsed = if (lastUncertaintyMs == Long.MIN_VALUE) Long.MAX_VALUE else nowMs - lastUncertaintyMs
        if (!force && elapsed < uncertaintyIntervalMs) return false
        val moved = if (lastUncertaintyLat == null || lastUncertaintyLon == null) true else
            Google3dCameraCommandGate.distanceM(lastUncertaintyLat!!, lastUncertaintyLon!!, latitudeDeg, longitudeDeg) >= 1.0
        val radiusChanged = when {
            radiusM == null || lastUncertaintyRadius == null -> radiusM != lastUncertaintyRadius
            else -> abs(radiusM - lastUncertaintyRadius!!) >= 0.5
        }
        if (!force && !moved && !radiusChanged && mode == lastUncertaintyMode && elapsed < uncertaintyMaximumSilenceMs) return false
        lastUncertaintyMs = nowMs
        lastUncertaintyLat = latitudeDeg
        lastUncertaintyLon = longitudeDeg
        lastUncertaintyRadius = radiusM
        lastUncertaintyMode = mode
        return true
    }
}
