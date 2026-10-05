package org.sih26168.idrlogger.map

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import org.sih26168.idrlogger.engine.LocalizationMode
import org.sih26168.idrlogger.engine.TrajectoryPoint
import org.sih26168.idrlogger.ui.Google3dMapSurface

class Google3dVisualPolicyTest {
    @Test fun sceneIsReadyOnlyAtCompleteReadiness() {
        assertFalse(Google3dMapSurface.sceneIsReady(Double.NaN))
        assertFalse(Google3dMapSurface.sceneIsReady(0.0))
        assertFalse(Google3dMapSurface.sceneIsReady(0.99))
        assertTrue(Google3dMapSurface.sceneIsReady(1.0))
    }

    @Test
    fun touchJitterDoesNotPauseFollowButDeliberateDragDoes() {
        val gate = FollowGestureGate(12f)
        gate.onDown(100f, 100f)
        assertFalse(gate.onMove(106f, 105f))
        assertTrue(gate.onMove(120f, 100f))
        assertFalse(gate.onMove(130f, 100f))
        gate.onEnd()
        assertFalse(gate.onMove(200f, 200f))
    }

    @Test
    fun pinchImmediatelyPausesFollow() {
        val gate = FollowGestureGate(12f)
        gate.onDown(100f, 100f)
        assertTrue(gate.onAdditionalPointer())
        assertFalse(gate.onAdditionalPointer())
        assertFalse(gate.onMove(140f, 140f))
    }

    @Test
    fun userInteractionCancelsDeferredFollowResume() {
        val guard = FollowResumeGuard()
        val routePreviewToken = guard.token()
        assertTrue(guard.isCurrent(routePreviewToken))
        guard.invalidate()
        assertFalse(guard.isCurrent(routePreviewToken))
    }

    @Test fun latestSlotCoalescesWithoutBuildingAQueue() {
        val slot = LatestValueSlot<String>()
        slot.offer("old")
        slot.offer("newest")
        assertEquals("newest", slot.takeLatest())
        assertEquals(2L, slot.offeredCount)
        assertEquals(1L, slot.supersededCount)
        assertFalse(slot.hasValue())
    }

    @Test fun cameraCommandsAreRateLimitedAndChangeGated() {
        val gate = Google3dCameraCommandGate()
        val pose = Google3dCameraVisualState(12.9716, 77.5946, 20.0, 65.0, 140.0)
        assertTrue(gate.shouldIssue(0L, pose))
        assertFalse(gate.shouldIssue(60L, pose.copy(latitudeDeg = 12.9720)))
        assertTrue(gate.shouldIssue(125L, pose.copy(latitudeDeg = 12.9720)))
        assertFalse(gate.shouldIssue(250L, pose.copy(latitudeDeg = 12.9720)))
        assertTrue(gate.shouldIssue(900L, pose.copy(latitudeDeg = 12.9720)))
    }

    @Test fun repeatedWorldScaleCameraMismatchFailsButOneTransientOnlyRetries() {
        val gate = Google3dCameraSanityGate()
        val expected = Google3dCameraVisualState(12.9716, 77.5946, 20.0, 58.0, 180.0)
        val wrong = expected.copy(latitudeDeg = 15.0, longitudeDeg = 78.0, rangeM = 900_000.0)
        assertEquals(CameraSanityAction.RETRY, gate.observe(expected, wrong, following = true))
        assertEquals(CameraSanityAction.NONE, gate.observe(expected, expected, following = true))
        assertEquals(CameraSanityAction.RETRY, gate.observe(expected, wrong, following = true))
        assertEquals(CameraSanityAction.FAIL, gate.observe(expected, wrong, following = true))
        assertEquals(CameraSanityAction.NONE, gate.observe(expected, wrong, following = false))
    }

    @Test fun rendererNetworkFallbackRequiresTwoConsecutiveFailures() {
        val gate = RendererNetworkGate()
        assertFalse(gate.shouldFallback(false))
        assertTrue(gate.shouldFallback(false))
        assertFalse(gate.shouldFallback(true))
        assertFalse(gate.shouldFallback(false))
    }

    @Test fun visualTrailIsBoundedAndPreservesEndpointsAndModeTransition() {
        val points = (0..1_999).map {
            TrajectoryPoint(it.toDouble(), 0.0, if (it < 1_000) LocalizationMode.GNSS_ACTIVE else LocalizationMode.IDR_ACTIVE)
        }
        val visual = Google3dVisualTrajectory.decimate(points)
        assertTrue(visual.size <= Google3dVisualTrajectory.MAXIMUM_POINTS)
        assertSame(points.first(), visual.first())
        assertSame(points.last(), visual.last())
        assertTrue(visual.any { it.localizationMode == LocalizationMode.IDR_ACTIVE })
    }

    @Test fun expensiveOverlaysHaveIndependentLowRateClocks() {
        val gate = Google3dOverlayGate()
        assertTrue(gate.shouldUpdateTrajectory(0L, 1L))
        assertFalse(gate.shouldUpdateTrajectory(500L, 2L))
        assertTrue(gate.shouldUpdateTrajectory(1_000L, 2L))
        assertTrue(gate.shouldUpdateUncertainty(0L, 12.0, 77.0, 5.0, LocalizationMode.GNSS_ACTIVE))
        assertFalse(gate.shouldUpdateUncertainty(500L, 12.001, 77.0, 5.0, LocalizationMode.GNSS_ACTIVE))
        assertTrue(gate.shouldUpdateUncertainty(750L, 12.001, 77.0, 5.0, LocalizationMode.GNSS_ACTIVE))
    }

    @Test fun monotonicSnapshotAgeRejectsMissingOrFutureTimestamps() {
        assertEquals(250.0, Google3dMapSurface.monotonicAgeMs(1_000_000_000L, 1_250_000_000L)!!, 0.0)
        assertEquals(null, Google3dMapSurface.monotonicAgeMs(0L, 1_250_000_000L))
        assertEquals(null, Google3dMapSurface.monotonicAgeMs(2_000_000_000L, 1_250_000_000L))
    }
}
