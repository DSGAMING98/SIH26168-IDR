package org.sih26168.idrlogger.map

import org.junit.Assert.*
import org.junit.Test
import org.sih26168.idrlogger.engine.LocalizationMode
import org.sih26168.idrlogger.engine.MotionState

class CinematicCameraTest {
    private val marker = EngineMarker(0.0, 0.0, 12.97, 77.59, 0.0)
    private fun frame(p: MapCameraPolicy, speed: Double, reliable: Boolean = true, m: EngineMarker = marker,
                      mode: LocalizationMode = LocalizationMode.GNSS_ACTIVE) =
        p.frame(m, speed, MotionState.MOVING, mode, reliable)!!

    @Test fun speedBandsHaveMeaningfulForwardCorridors() {
        assertEquals(0.0, frame(MapCameraPolicy(), 0.0).lookAheadM, 0.0)
        assertTrue(frame(MapCameraPolicy(), 5.0).lookAheadM in 15.0..35.0)
        assertTrue(frame(MapCameraPolicy(), 15.0).lookAheadM in 35.0..70.0)
        assertTrue(frame(MapCameraPolicy(), 30.0).lookAheadM in 70.0..120.0)
    }

    @Test fun targetZoomTiltAndLookAheadAreDampedIndependently() {
        val policy = MapCameraPolicy()
        val first = frame(policy, 5.0)
        val moved = marker.copy(latitudeDeg = 12.971)
        val next = frame(policy, 30.0, m = moved)
        val raw = frame(MapCameraPolicy(), 30.0, m = moved)
        assertTrue(next.target.latitudeDeg > first.target.latitudeDeg)
        assertTrue(next.target.latitudeDeg < raw.target.latitudeDeg)
        assertTrue(next.lookAheadM > first.lookAheadM && next.lookAheadM < raw.lookAheadM)
        assertTrue(next.zoom < first.zoom && next.zoom > raw.zoom)
        assertTrue(next.tiltDeg > first.tiltDeg && next.tiltDeg < raw.tiltDeg)
    }

    @Test fun poorConfidenceCannotInitializeOrRotateCameraBearing() {
        val policy = MapCameraPolicy()
        assertEquals(0f, frame(policy, 15.0, false, marker.copy(headingDeg = 90.0)).bearingDeg, 0f)
        val stable = frame(policy, 15.0, true, marker.copy(headingDeg = 90.0)).bearingDeg
        assertEquals(90f, stable, 0f)
        assertEquals(stable, frame(policy, 15.0, false, marker.copy(headingDeg = 270.0)).bearingDeg, 0f)
    }

    @Test fun bearingHysteresisAvoidsChatteringNearSpeedThreshold() {
        val policy = MapCameraPolicy()
        frame(policy, 3.0)
        val moving = policy.bearing(90.0, 1.7)
        assertTrue(moving > 0f)
        assertEquals(moving, policy.bearing(270.0, 0.8), 0f)
        assertEquals(moving, policy.bearing(270.0, 1.7), 0f)
        assertNotEquals(moving, policy.bearing(90.0, 2.1))
    }

    @Test fun northUpIsFlatWithoutForwardOffsetUntilRecenter() {
        val p = MapCameraPolicy(headingUp = false)
        val north = frame(p, 15.0)
        assertEquals(0f, north.bearingDeg, 0f)
        assertEquals(0f, north.tiltDeg, 0f)
        assertEquals(0.0, north.lookAheadM, 0.0)
        p.recenter()
        assertTrue(p.headingUp)
        assertTrue(frame(p, 15.0).tiltDeg > 0f)
    }

    @Test fun idrAndRecoveryKeepFollowingEngineCoordinatesWithoutReset() {
        val p = MapCameraPolicy()
        var last = frame(p, 15.0)
        for ((index, mode) in listOf(LocalizationMode.GNSS_DEGRADED, LocalizationMode.IDR_ACTIVE,
            LocalizationMode.GNSS_VERIFYING, LocalizationMode.GNSS_RECOVERING, LocalizationMode.GNSS_ACTIVE).withIndex()) {
            val next = frame(p, 15.0, m = marker.copy(latitudeDeg = 12.97 + (index + 1) * 0.0001), mode = mode)
            assertTrue(p.following)
            assertTrue(next.target.latitudeDeg > last.target.latitudeDeg)
            assertEquals(last.tiltDeg, next.tiltDeg, 0f)
            assertEquals(last.zoom, next.zoom, 0f)
            last = next
        }
    }

    @Test fun cameraUpdatesAtMostFourTimesPerSecond() {
        val p = MapCameraPolicy()
        assertTrue(p.shouldUpdate(1000))
        assertFalse(p.shouldUpdate(1249))
        assertTrue(p.shouldUpdate(1250))
    }

    @Test fun datelineInterpolationTakesShortArc() {
        val p = MapCameraPolicy()
        frame(p, 15.0, m = marker.copy(longitudeDeg = 179.999))
        val next = frame(p, 15.0, m = marker.copy(longitudeDeg = -179.999))
        assertTrue(kotlin.math.abs(next.target.longitudeDeg) > 179.99)
    }

    @Test fun stoppedBearingAndLookAheadSettleWithoutSpinning() {
        val p = MapCameraPolicy()
        frame(p, 15.0, m = marker.copy(headingDeg = 90.0))
        var last = frame(p, 0.0, m = marker.copy(headingDeg = 270.0))
        repeat(80) { last = frame(p, 0.0, m = marker.copy(headingDeg = it * 51.0)) }
        assertEquals(90f, last.bearingDeg, 0f)
        assertTrue(last.lookAheadM < 0.01)
    }
}
