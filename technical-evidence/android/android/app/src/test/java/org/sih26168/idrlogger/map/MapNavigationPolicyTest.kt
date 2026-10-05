package org.sih26168.idrlogger.map

import org.junit.Assert.*
import org.junit.Test
import org.sih26168.idrlogger.engine.LocalizationMode
import org.sih26168.idrlogger.engine.MotionState
import org.sih26168.idrlogger.engine.NavigationSnapshot
import org.sih26168.idrlogger.engine.NavigationState
import org.sih26168.idrlogger.engine.TrajectoryPoint

class MapNavigationPolicyTest {
    private fun snapshot(mode: LocalizationMode = LocalizationMode.GNSS_ACTIVE, heading: Double = 90.0) = NavigationSnapshot(
        state = NavigationState(latitudeDeg = 12.97, longitudeDeg = 77.59, eastM = 12.0, northM = -8.0,
            speedMps = 12.0, headingDeg = heading, localizationMode = mode, motionState = MotionState.MOVING,
            horizontalUncertaintyM = 24.0),
        trajectory = listOf(TrajectoryPoint(12.0, -8.0, mode)),
    )

    private fun frame(policy: MapCameraPolicy, snapshot: NavigationSnapshot) = policy.frame(
        EngineMarkerPolicy.from(snapshot), snapshot.state.speedMps, snapshot.state.motionState, snapshot.state.localizationMode,
    )!!

    @Test fun firstMovingFrameUsesEngineHeadingWithNavigationPerspective() {
        val frame = frame(MapCameraPolicy(), snapshot())
        assertEquals(90f, frame.bearingDeg, 0f)
        assertTrue(frame.tiltDeg in 59f..66f)
        assertTrue(frame.target.longitudeDeg > 77.59)
    }

    @Test fun cameraLookAheadCannotChangeEngineMarkerTrajectoryOrSnapshot() {
        val snapshot = snapshot()
        val before = snapshot.copy()
        val marker = EngineMarkerPolicy.from(snapshot)
        val frame = frame(MapCameraPolicy(), snapshot)
        assertTrue(frame.lookAheadM > 0.0)
        assertNotEquals(marker.longitudeDeg, frame.target.longitudeDeg)
        assertEquals(before, snapshot)
        assertEquals(marker, EngineMarkerPolicy.from(snapshot))
        assertEquals(12.0, snapshot.trajectory.single().eastM, 0.0)
    }

    @Test fun lookAheadIsBoundedEvenAtExtremeReportedSpeed() {
        val value = snapshot().let { it.copy(state = it.state.copy(speedMps = 500.0)) }
        assertEquals(MapCameraPolicy.MAXIMUM_LOOK_AHEAD_M, frame(MapCameraPolicy(), value).lookAheadM, 0.0)
    }

    @Test fun lowSpeedAndStationaryHoldTheLastStableBearing() {
        val policy = MapCameraPolicy()
        val stable = frame(policy, snapshot()).bearingDeg
        assertEquals(stable, policy.bearing(270.0, 0.4, MotionState.MOVING), 0f)
        assertEquals(stable, policy.bearing(270.0, 20.0, MotionState.LIKELY_STATIONARY), 0f)
        assertEquals(stable, policy.bearing(Double.NaN, 20.0), 0f)
        assertEquals(stable, policy.bearing(270.0, Double.NaN), 0f)
    }

    @Test fun stationaryLookAheadIsZeroWithoutChangingEstimatedPosition() {
        val original = snapshot()
        val stopped = original.copy(state = original.state.copy(speedMps = 0.0, motionState = MotionState.LIKELY_STATIONARY))
        val frame = frame(MapCameraPolicy(), stopped)
        assertEquals(0.0, frame.lookAheadM, 0.0)
        assertEquals(stopped.state.latitudeDeg!!, frame.target.latitudeDeg, 1e-12)
        assertEquals(stopped.state.longitudeDeg!!, frame.target.longitudeDeg, 1e-12)
    }

    @Test fun wrapAroundUsesTheShortCircularTransition() {
        val policy = MapCameraPolicy()
        frame(policy, snapshot(heading = 359.0))
        val next = policy.bearing(1.0, 10.0)
        assertTrue(next > 359f || next < 2f)
        assertEquals(next, policy.bearing(next.toDouble() + 0.2, 10.0), 0f)
        assertEquals(1.0, MapCameraPolicy.normalizeBearing(721.0), 0.0)
        assertEquals(359.0, MapCameraPolicy.normalizeBearing(-721.0), 0.0)
    }

    @Test fun gesturesSuspendAllCameraUpdatesAndRecenterOverridesThrottleImmediately() {
        val policy = MapCameraPolicy()
        assertTrue(policy.shouldUpdate(1_000))
        policy.onUserGesture()
        assertFalse(policy.shouldUpdate(5_000))
        policy.recenter()
        assertTrue(policy.shouldUpdate(5_000))
        assertFalse(policy.shouldUpdate(5_001))
        policy.recenter()
        assertTrue(policy.shouldUpdate(5_002))
    }

    @Test fun recenterRestoresCinematicEvenAfterNorthUp() {
        val policy = MapCameraPolicy(headingUp = false)
        policy.onUserGesture(); policy.recenter()
        val frame = frame(policy, snapshot())
        assertTrue(policy.following)
        assertEquals(90f, frame.bearingDeg, 0f)
        assertTrue(frame.tiltDeg >= 59f)
        assertTrue(frame.lookAheadM > 0.0)
    }

    @Test fun blackoutAndRecoveryPreserve3dEngineOwnedMarkerAndUncertainty() {
        for (mode in listOf(LocalizationMode.IDR_ACTIVE, LocalizationMode.GNSS_VERIFYING, LocalizationMode.GNSS_RECOVERING)) {
            val snapshot = snapshot(mode)
            val marker = EngineMarkerPolicy.from(snapshot)
            val frame = frame(MapCameraPolicy(), snapshot)
            assertTrue(frame.tiltDeg in 59f..66f)
            assertEquals(snapshot.state.latitudeDeg, marker.latitudeDeg)
            assertEquals(snapshot.state.longitudeDeg, marker.longitudeDeg)
            assertEquals(24.0, snapshot.state.horizontalUncertaintyM!!, 0.0)
        }
    }

    @Test fun unavailableCoordinatesNeverFabricateACameraPosition() {
        val policy = MapCameraPolicy()
        assertNull(policy.frame(EngineMarkerPolicy.from(NavigationSnapshot()), 0.0, MotionState.INITIALIZING, LocalizationMode.WAITING_FOR_GNSS))
        val invalid = EngineMarker(0.0, 0.0, Double.NaN, 77.0, 0.0)
        assertNull(policy.frame(invalid, 0.0, MotionState.INITIALIZING, LocalizationMode.WAITING_FOR_GNSS))
    }

    @Test fun onlyAnActualErrorUsesRedAndRecoveryUsesPurple() {
        assertEquals(0xFF4AD8B5.toInt(), MapStateStyle.color(LocalizationMode.GNSS_ACTIVE))
        assertEquals(0xFFFFAE48.toInt(), MapStateStyle.color(LocalizationMode.IDR_ACTIVE))
        assertEquals(0xFF967EFF.toInt(), MapStateStyle.color(LocalizationMode.GNSS_RECOVERING))
        for (mode in LocalizationMode.entries.filter { it != LocalizationMode.ERROR })
            assertNotEquals(MapStateStyle.color(LocalizationMode.ERROR), MapStateStyle.color(mode))
    }

    @Test fun mapReadinessRequiresActualTilesBeforeTheBoundedTimeout() {
        val policy = MapLoadPolicy()
        policy.begin(1_000)
        assertFalse(policy.loaded)
        assertFalse(policy.timedOut(12_999))
        assertTrue(policy.onTilesLoaded(12_999))
        assertTrue(policy.loaded)
        assertFalse(policy.loading)
    }

    @Test fun mapTimeoutRejectsLateCallbacksAndAllowsAnExplicitNewLoad() {
        val policy = MapLoadPolicy()
        policy.begin(1_000)
        assertTrue(policy.timedOut(13_000))
        assertFalse(policy.onTilesLoaded(13_000))
        assertFalse(policy.loaded)
        policy.begin(20_000)
        assertTrue(policy.onTilesLoaded(20_100))
        policy.fail()
        assertFalse(policy.loaded)
        assertFalse(policy.onTilesLoaded(20_200))
    }
}
