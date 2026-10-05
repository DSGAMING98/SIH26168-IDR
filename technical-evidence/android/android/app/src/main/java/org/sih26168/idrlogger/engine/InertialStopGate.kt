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
    private val stationaryConfirmationS: Double = 1.50,
    private val armedDurationS: Double = 12.0,
    private val departureEvidenceS: Double = 0.80,
    private val departureRearmCooldownS: Double = 15.0,
) {
    private var brakingS = 0.0
    private var stationaryS = 0.0
    private var armedRemainingS = 0.0
    private var departureS = 0.0
    private var rearmCooldownS = 0.0
    private var confirmed = false
    var justReleasedStop: Boolean = false
        private set

    fun reset() {
        brakingS = 0.0
        stationaryS = 0.0
        armedRemainingS = 0.0
        departureS = 0.0
        rearmCooldownS = 0.0
        confirmed = false
        justReleasedStop = false
    }

    fun update(dtS: Double, motion: ConditionedMotion): Boolean {
        justReleasedStop = false
        if (!dtS.isFinite() || dtS <= 0.0) return confirmed

        if (rearmCooldownS > 0.0) rearmCooldownS = (rearmCooldownS - dtS).coerceAtLeast(0.0)

        // A confirmed stop is a latch, but it must not become permanent when a metro departs
        // smoothly. SensorConditioner deliberately calls constant-speed travel stationary-looking
        // because an IMU cannot distinguish it from rest. Release the latch from sustained launch
        // dynamics, then clear the old stop evidence so that the following smooth cruise is not
        // immediately interpreted as a second station stop.
        if (confirmed) {
            val departureDynamics = motion.motionState == MotionState.MOVING ||
                motion.accelerationRmsMps2 >= DEPARTURE_ACCELERATION_RMS_MPS2 ||
                abs(motion.forwardAccelerationMps2) >= DEPARTURE_ACCELERATION_MPS2
            departureS = if (departureDynamics) departureS + dtS else (departureS - dtS).coerceAtLeast(0.0)
            if (departureS + TIME_EPSILON_S >= departureEvidenceS) {
                confirmed = false
                departureS = 0.0
                brakingS = 0.0
                stationaryS = 0.0
                armedRemainingS = 0.0
                rearmCooldownS = departureRearmCooldownS
                justReleasedStop = true
            } else {
                return true
            }
        }

        if (motion.motionState == MotionState.MOVING) {
            stationaryS = 0.0
            val braking = motion.forwardAccelerationMps2 <= brakingAccelerationMps2
            brakingS = if (braking) brakingS + dtS else (brakingS - dtS).coerceAtLeast(0.0)
            val brakingArmed = brakingS >= brakingEvidenceS
            if (brakingArmed && rearmCooldownS <= 0.0) {
                armedRemainingS = armedDurationS
            }
        } else {
            brakingS = (brakingS - dtS).coerceAtLeast(0.0)
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
        private const val DEPARTURE_ACCELERATION_RMS_MPS2 = 0.30
        private const val DEPARTURE_ACCELERATION_MPS2 = 0.25
        private const val TIME_EPSILON_S = 1e-9
    }
}
