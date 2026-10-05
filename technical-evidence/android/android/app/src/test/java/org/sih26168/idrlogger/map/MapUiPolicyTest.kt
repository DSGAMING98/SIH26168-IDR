package org.sih26168.idrlogger.map

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.sih26168.idrlogger.engine.LocalizationMode
import org.sih26168.idrlogger.engine.MotionState

class MapUiPolicyTest {
    @Test fun currentEnginePositionProjectsToItsOwnGeographicFix() {
        val point = MapCoordinateProjector.fromCurrentEnginePosition(
            pointEastM = 120.0,
            pointNorthM = -35.0,
            currentEastM = 120.0,
            currentNorthM = -35.0,
            currentLatitudeDeg = 12.9716,
            currentLongitudeDeg = 77.5946,
        )
        assertEquals(12.9716, point.latitudeDeg, 1e-12)
        assertEquals(77.5946, point.longitudeDeg, 1e-12)
    }

    @Test fun localNorthAndEastOffsetsProjectWithCorrectSigns() {
        val point = MapCoordinateProjector.fromCurrentEnginePosition(100.0, 100.0, 0.0, 0.0, 12.0, 77.0)
        assertTrue(point.latitudeDeg > 12.0)
        assertTrue(point.longitudeDeg > 77.0)
    }

    @Test fun cameraUpdatesAreThrottledAndGesturesSuspendFollow() {
        val policy = MapCameraPolicy(minimumUpdateIntervalMs = 750L)
        assertTrue(policy.shouldUpdate(1_000L))
        assertFalse(policy.shouldUpdate(1_749L))
        assertTrue(policy.shouldUpdate(1_750L))
        policy.onUserGesture()
        assertFalse(policy.following)
        assertFalse(policy.shouldUpdate(3_000L))
        policy.recenter()
        assertTrue(policy.following)
        assertTrue(policy.shouldUpdate(3_000L))
    }

    @Test fun northUpIgnoresHeadingAndHeadingUpChangesSmoothly() {
        assertEquals(0f, MapCameraPolicy(headingUp = false).bearing(243.0), 0f)
        val headingUp = MapCameraPolicy(headingUp = true)
        val first = headingUp.bearing(90.0)
        assertTrue(first in 0f..7f)
        assertTrue(headingUp.bearing(90.0) > first)
    }

    @Test fun largePositionCorrectionSnapsCameraToNewestEngineFix() {
        val policy = MapCameraPolicy()
        val first = EngineMarker(0.0, 0.0, 12.9716, 77.5946, 0.0)
        policy.frame(first, 0.0, MotionState.LIKELY_STATIONARY, LocalizationMode.GNSS_ACTIVE)
        val corrected = first.copy(latitudeDeg = 12.9816, longitudeDeg = 77.6046)
        val frame = policy.frame(corrected, 0.0, MotionState.LIKELY_STATIONARY, LocalizationMode.GNSS_ACTIVE)!!
        assertEquals(corrected.latitudeDeg!!, frame.target.latitudeDeg, 1e-12)
        assertEquals(corrected.longitudeDeg!!, frame.target.longitudeDeg, 1e-12)
    }

    @Test fun recenterDropsStaleCameraTarget() {
        val policy = MapCameraPolicy()
        val first = EngineMarker(0.0, 0.0, 12.9716, 77.5946, 0.0)
        policy.frame(first, 0.0, MotionState.LIKELY_STATIONARY, LocalizationMode.GNSS_ACTIVE)
        policy.onUserGesture()
        policy.recenter()
        val current = first.copy(latitudeDeg = 12.9720, longitudeDeg = 77.5950)
        val frame = policy.frame(current, 0.0, MotionState.LIKELY_STATIONARY, LocalizationMode.GNSS_ACTIVE)!!
        assertEquals(current.latitudeDeg!!, frame.target.latitudeDeg, 1e-12)
        assertEquals(current.longitudeDeg!!, frame.target.longitudeDeg, 1e-12)
    }
}
