package org.sih26168.idrlogger.engine

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class InertialStopGateTest {
    @Test
    fun smoothCoastingCannotBeMistakenForAStop() {
        val gate = InertialStopGate()
        repeat(300) {
            assertFalse(gate.update(0.1, motion(MotionState.LIKELY_STATIONARY, 0.0, 0.01)))
        }
    }

    @Test
    fun vehicleDynamicsFollowedByStableRestConfirmsAStop() {
        val gate = InertialStopGate()
        repeat(12) { assertFalse(gate.update(0.1, motion(MotionState.MOVING, -0.65, 0.7))) }
        var stopped = false
        repeat(20) { stopped = gate.update(0.1, motion(MotionState.LIKELY_STATIONARY, 0.0, 0.02)) }
        assertTrue(stopped)
    }

    @Test
    fun stationDepartureReleasesStopWithoutRefreezingDuringSmoothCruise() {
        val gate = InertialStopGate()
        repeat(12) { gate.update(0.1, motion(MotionState.MOVING, -0.65, 0.7)) }
        var held = false
        repeat(20) { held = gate.update(0.1, motion(MotionState.LIKELY_STATIONARY, 0.0, 0.02)) }
        assertTrue(held)

        repeat(7) {
            assertTrue(
                "the confirmed stop should remain latched until departure is sustained",
                gate.update(0.1, motion(MotionState.LIKELY_STATIONARY, 0.32, 0.34)),
            )
        }
        assertFalse(gate.update(0.1, motion(MotionState.LIKELY_STATIONARY, 0.32, 0.34)))

        repeat(250) {
            assertFalse(
                "departure acceleration must not arm a false stop during the following cruise",
                gate.update(0.1, motion(MotionState.LIKELY_STATIONARY, 0.0, 0.02)),
            )
        }
    }

    @Test
    fun brakingAfterDepartureCanConfirmTheNextStationStop() {
        val gate = InertialStopGate()
        repeat(12) { gate.update(0.1, motion(MotionState.MOVING, -0.65, 0.7)) }
        repeat(20) { gate.update(0.1, motion(MotionState.LIKELY_STATIONARY, 0.0, 0.02)) }
        repeat(10) { gate.update(0.1, motion(MotionState.MOVING, 0.7, 0.8)) }
        repeat(160) { gate.update(0.1, motion(MotionState.LIKELY_STATIONARY, 0.0, 0.02)) }
        repeat(8) { gate.update(0.1, motion(MotionState.MOVING, -0.7, 0.8)) }
        var stopped = false
        repeat(20) { stopped = gate.update(0.1, motion(MotionState.LIKELY_STATIONARY, 0.0, 0.02)) }
        assertTrue(stopped)
    }

    private fun motion(state: MotionState, forward: Double, rms: Double) = ConditionedMotion(
        forwardAccelerationMps2 = forward,
        leftAccelerationMps2 = 0.0,
        yawRateRadps = 0.0,
        gyroMagnitudeRadps = 0.0,
        gravityMagnitudeMps2 = 9.80665,
        magneticMagnitudeUt = 38.0,
        accelerationRmsMps2 = rms,
        gyroRmsRadps = 0.0,
        deviceHeadingRad = 0.0,
        motionState = state,
        attitudeAvailable = true,
    )
}
