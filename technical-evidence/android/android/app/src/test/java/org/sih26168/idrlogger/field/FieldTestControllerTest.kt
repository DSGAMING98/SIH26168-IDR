package org.sih26168.idrlogger.field

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.sih26168.idrlogger.model.FieldTestPhase
import org.sih26168.idrlogger.model.FieldTestPreset
import org.sih26168.idrlogger.model.MountProfile

class FieldTestControllerTest {
    @Test
    fun automaticScheduleWaitsForReadinessThenRunsWithoutDriverInput() {
        val controller = FieldTestController()
        val start = 1_000_000_000L
        assertEquals(
            FieldTestPhase.WARMUP,
            controller.start(start, "TEST_SHORT", FieldTestPreset.SHORT, MountProfile.DASHBOARD).status.phase,
        )
        assertEquals(
            FieldTestPhase.WAITING_FOR_READY,
            controller.update(start + 30_000_000_000L, alignmentReady = false, runtimeGnssAvailable = true).status.phase,
        )
        val baseline = controller.update(start + 35_000_000_000L, true, true)
        assertEquals(FieldTestPhase.BASELINE, baseline.status.phase)
        val blackout = controller.update(start + 55_000_000_000L, true, true)
        assertEquals(FieldTestPhase.BLACKOUT, blackout.status.phase)
        assertTrue(blackout.status.blackoutActive)
        assertTrue(blackout.events.any { it.type == "FIELD_TEST_BLACKOUT_STARTED" })
        val recovery = controller.update(start + 65_000_000_000L, true, true)
        assertEquals(FieldTestPhase.RECOVERY, recovery.status.phase)
        assertFalse(recovery.status.blackoutActive)
        assertTrue(recovery.events.any { it.type == "FIELD_TEST_BLACKOUT_ENDED" })
        val complete = controller.update(start + 95_000_000_000L, true, true)
        assertEquals(FieldTestPhase.COMPLETE, complete.status.phase)
        assertTrue(complete.events.any { it.type == "FIELD_TEST_COMPLETED" })
    }

    @Test
    fun allPresetsExposeRequestedBlackoutDurations() {
        assertEquals(listOf(10, 30, 60, 120), FieldTestPreset.entries.map { it.blackoutDurationSeconds })
    }

    @Test
    fun cancellationAlwaysReleasesAutomaticBlackout() {
        val controller = FieldTestController()
        val start = 1_000_000_000L
        controller.start(start, "TEST", FieldTestPreset.MEDIUM, MountProfile.UNKNOWN)
        controller.update(start + 30_000_000_000L, true, true)
        controller.update(start + 50_000_000_000L, true, true)
        assertTrue(controller.snapshot().blackoutActive)
        val cancelled = controller.cancel(start + 51_000_000_000L)
        assertEquals(FieldTestPhase.CANCELLED, cancelled.status.phase)
        assertFalse(cancelled.status.blackoutActive)
    }
}
