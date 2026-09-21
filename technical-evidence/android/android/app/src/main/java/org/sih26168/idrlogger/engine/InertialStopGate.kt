package org.sih26168.idrlogger.engine

import kotlin.math.abs

/**
 * Confirms a stop without trusting the already-integrated EKF speed.
 *
 * Constant velocity and rest are indistinguishable to an IMU, so low vibration alone must never
 * zero a moving estimate. The gate first requires causal evidence of braking or sustained vehicle
 * dynamics, then a stable stationary window. This lets a metro stop recover even after velocity
 * drift, while preserving ordinary coasting through a GNSS blackout.
 */
class InertialStopGate(
    private val brakingAccelerationMps2: Double = -0.45,
    private val brakingEvidenceS: Double = 0.30,
    private val dynamicEvidenceS: Double = 0.80,
    private val stationaryConfirmationS: Double = 1.50,
    private val armedDurationS: Double = 45.0,
) {
    private var brakingS = 0.0
    private var dynamicS = 0.0
    private var stationaryS = 0.0
    private var armedRemainingS = 0.0
    private var confirmed = false

    fun reset() {
        brakingS = 0.0
        dynamicS = 0.0
        stationaryS = 0.0
        armedRemainingS = 0.0
        confirmed = false
    }

    fun update(dtS: Double, motion: ConditionedMotion): Boolean {
        if (!dtS.isFinite() || dtS <= 0.0) return confirmed

        if (motion.motionState == MotionState.MOVING) {
            confirmed = false
            stationaryS = 0.0
            val braking = motion.forwardAccelerationMps2 <= brakingAccelerationMps2
            brakingS = if (braking) brakingS + dtS else (brakingS - dtS).coerceAtLeast(0.0)
            val dynamic = motion.accelerationRmsMps2 >= DYNAMIC_ACCELERATION_RMS_MPS2 ||
                abs(motion.forwardAccelerationMps2) >= DYNAMIC_ACCELERATION_MPS2
            dynamicS = if (dynamic) dynamicS + dtS else (dynamicS - dtS * 0.5).coerceAtLeast(0.0)
            if (brakingS >= brakingEvidenceS || dynamicS >= dynamicEvidenceS) {
                armedRemainingS = armedDurationS
            }
        } else {
            brakingS = (brakingS - dtS).coerceAtLeast(0.0)
            dynamicS = (dynamicS - dtS * 0.25).coerceAtLeast(0.0)
        }

        if (armedRemainingS > 0.0) armedRemainingS = (armedRemainingS - dtS).coerceAtLeast(0.0)
        if (motion.motionState == MotionState.LIKELY_STATIONARY && armedRemainingS > 0.0) {
            stationaryS += dtS
            if (stationaryS >= stationaryConfirmationS) confirmed = true
        } else if (!confirmed) {
            stationaryS = 0.0
        }
        return confirmed
    }

    companion object {
        private const val DYNAMIC_ACCELERATION_RMS_MPS2 = 0.45
        private const val DYNAMIC_ACCELERATION_MPS2 = 0.35
    }
}
