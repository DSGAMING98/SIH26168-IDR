package org.sih26168.idrlogger.map

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.sih26168.idrlogger.engine.LocalizationMode
import org.sih26168.idrlogger.engine.MotionState

class True3dCameraPolicyTest {
    private val marker = EngineMarker(0.0, 0.0, 12.9716, 77.5946, 355.0)

    @Test fun usesReal3dPitchAndUrbanLookAhead() {
        val frame = True3dCameraPolicy().frame(marker, 12.0, MotionState.MOVING, LocalizationMode.GNSS_ACTIVE, true)!!
        assertTrue(frame.pitchDeg in 56.0..66.0)
        assertTrue(frame.lookAheadM in 15.0..40.0)
        assertTrue(frame.zoom <= 17.15)
    }

    @Test fun headingWrapTakesShortArc() {
        val policy = True3dCameraPolicy()
        policy.frame(marker.copy(headingDeg = 359.0), 10.0, MotionState.MOVING, LocalizationMode.IDR_ACTIVE, true)
        val frame = policy.frame(marker.copy(headingDeg = 1.0), 10.0, MotionState.MOVING, LocalizationMode.IDR_ACTIVE, true)!!
        assertTrue(frame.bearingDeg < 5.0 || frame.bearingDeg > 355.0)
    }

    @Test fun stationaryInputHoldsBearingAndRemovesLookAhead() {
        val policy = True3dCameraPolicy()
        val moving = policy.frame(marker.copy(headingDeg = 45.0), 10.0, MotionState.MOVING, LocalizationMode.GNSS_ACTIVE, true)!!
        val still = policy.frame(marker.copy(headingDeg = 220.0), 0.0, MotionState.LIKELY_STATIONARY, LocalizationMode.GNSS_ACTIVE, true)!!
        assertEquals(moving.bearingDeg, still.bearingDeg, 0.001)
        assertEquals(0.0, still.lookAheadM, 0.0)
        assertEquals(marker.latitudeDeg!!, still.target.latitudeDeg, 1e-12)
        assertEquals(marker.longitudeDeg!!, still.target.longitudeDeg, 1e-12)
    }

    @Test fun gesturePausesAndRecenterRestoresFollow() {
        val policy = True3dCameraPolicy()
        assertTrue(policy.shouldUpdate(100))
        policy.onUserGesture()
        assertFalse(policy.shouldUpdate(1000))
        policy.recenter()
        assertTrue(policy.shouldUpdate(1001))
    }

    @Test fun firstValidPositionIsImmediateAndLargeRelocationDoesNotChase() {
        val policy = True3dCameraPolicy()
        val first = policy.frame(marker, 0.0, MotionState.LIKELY_STATIONARY, LocalizationMode.CALIBRATING, false)!!
        assertEquals(marker.latitudeDeg!!, first.target.latitudeDeg, 1e-12)
        assertEquals(marker.longitudeDeg!!, first.target.longitudeDeg, 1e-12)

        val relocated = marker.copy(latitudeDeg = 12.9816, longitudeDeg = 77.6046)
        val caughtUp = policy.frame(relocated, 0.0, MotionState.LIKELY_STATIONARY, LocalizationMode.CALIBRATING, false)!!
        assertEquals(relocated.latitudeDeg!!, caughtUp.target.latitudeDeg, 1e-12)
        assertEquals(relocated.longitudeDeg!!, caughtUp.target.longitudeDeg, 1e-12)
    }
}
