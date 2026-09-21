package org.sih26168.idrlogger.engine

import java.util.ArrayDeque
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.sin

class VehicleAlignment(
    private val minimumSamples: Int = 5,
    private val minimumSpeedMps: Double = 2.5,
) {
    private val offsets = ArrayDeque<Double>()
    var state: AlignmentState = AlignmentState.CALIBRATING
        private set
    var yawOffsetRad: Double? = null
        private set
    val progress: Double
        get() = if (state == AlignmentState.READY) 1.0 else (offsets.size.toDouble() / minimumSamples).coerceIn(0.0, 1.0)

    fun reset() {
        offsets.clear()
        state = AlignmentState.CALIBRATING
        yawOffsetRad = null
    }

    fun update(deviceHeadingRad: Double?, gnssBearingDeg: Double?, speedMps: Double?): AlignmentState {
        if (deviceHeadingRad == null || !deviceHeadingRad.isFinite()) {
            if (yawOffsetRad == null) state = AlignmentState.DEGRADED
            return state
        }
        if (gnssBearingDeg == null || speedMps == null || speedMps < minimumSpeedMps) {
            if (yawOffsetRad == null) state = AlignmentState.CALIBRATING
            return state
        }
        val offset = wrapAngleRad(Math.toRadians(gnssBearingDeg) - deviceHeadingRad)
        offsets.addLast(offset)
        while (offsets.size > MAX_ALIGNMENT_SAMPLES) offsets.removeFirst()
        if (offsets.size >= minimumSamples) {
            val x = offsets.sumOf(::cos)
            val y = offsets.sumOf(::sin)
            val concentration = hypot(x, y) / offsets.size
            if (concentration >= MINIMUM_CONCENTRATION) {
                yawOffsetRad = atan2(y, x)
                state = AlignmentState.READY
            } else {
                state = AlignmentState.CALIBRATING
            }
        }
        return state
    }

    fun vehicleHeading(deviceHeadingRad: Double?): Double? {
        val offset = yawOffsetRad ?: return null
        return deviceHeadingRad?.let { wrapAngleRad(it + offset) }
    }

    companion object {
        private const val MAX_ALIGNMENT_SAMPLES = 30
        private const val MINIMUM_CONCENTRATION = 0.80
    }
}
