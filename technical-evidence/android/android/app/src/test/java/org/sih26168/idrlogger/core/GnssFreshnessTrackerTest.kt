package org.sih26168.idrlogger.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.sih26168.idrlogger.model.GnssStatus
import org.sih26168.idrlogger.model.PhysicalGnssFix
import org.sih26168.idrlogger.model.PhysicalGnssState
import org.sih26168.idrlogger.model.RuntimeGnssAvailability

class GnssFreshnessTrackerTest {
    private fun fix(timeNs: Long, latitude: Double = 12.9716) = PhysicalGnssFix(
        monotonicTimestampNs = timeNs,
        wallClockUtc = "2026-01-01T00:00:00Z",
        latitudeDeg = latitude,
        longitudeDeg = 77.5946,
        altitudeM = 900.0,
        speedMps = 5.0,
        bearingDeg = 90.0,
        accuracyM = 3.0,
        verticalAccuracyM = null,
        speedAccuracyMps = null,
        bearingAccuracyDeg = null,
        provider = "gps",
    )

    @Test
    fun startsWaitingForFirstFix() {
        val tracker = GnssFreshnessTracker()
        tracker.reset(1_000_000_000L)

        val state = tracker.runtimeState(1_500_000_000L, false)
        val diagnostics = tracker.diagnostics(1_500_000_000L, false)
        assertEquals(GnssStatus.WAITING_FOR_FIRST_FIX, state.status)
        assertEquals(0L, diagnostics.physicalCallbackCount)
        assertNull(diagnostics.firstValidFixTimestampNs)
        assertNull(diagnostics.timeToFirstFixSeconds)
    }

    @Test
    fun firstValidFixTransitionsToFreshAndRecordsTiming() {
        val tracker = GnssFreshnessTracker()
        tracker.reset(1_000_000_000L)

        assertEquals(GnssStatus.FRESH, tracker.accept(fix(1_500_000_000L), 1_600_000_000L))
        val diagnostics = tracker.diagnostics(1_700_000_000L, false)
        assertEquals(GnssStatus.FRESH, tracker.runtimeState(1_700_000_000L, false).status)
        assertEquals(1_500_000_000L, diagnostics.firstValidFixTimestampNs)
        assertEquals(0.6, diagnostics.timeToFirstFixSeconds!!, 1e-12)
    }

    @Test
    fun physicalCallbackCountIncludesInvalidCallbacks() {
        val tracker = GnssFreshnessTracker()
        tracker.reset(1_000_000_000L)
        tracker.accept(fix(1_100_000_000L, 100.0), 1_100_000_000L)
        tracker.accept(fix(1_200_000_000L), 1_200_000_000L)

        val diagnostics = tracker.diagnostics(1_300_000_000L, false)
        assertEquals(2L, diagnostics.physicalCallbackCount)
        assertEquals(1_200_000_000L, diagnostics.lastPhysicalGnssTimestampNs)
        assertEquals(0.1, diagnostics.latestPhysicalCallbackAgeSeconds!!, 1e-12)
    }

    @Test
    fun blackoutBeforeFirstFixDoesNotClaimRealMasking() {
        val tracker = GnssFreshnessTracker()
        tracker.reset(1_000_000_000L)

        assertEquals(GnssStatus.SIMULATED_BLACKOUT, tracker.runtimeState(1_100_000_000L, true).status)
        assertFalse(tracker.diagnostics(1_100_000_000L, true).blackoutMasksRealFix)
    }

    @Test
    fun blackoutAfterFirstFixClaimsRealMasking() {
        val tracker = GnssFreshnessTracker()
        tracker.reset(1_000_000_000L)
        tracker.accept(fix(1_100_000_000L), 1_100_000_000L)

        assertTrue(tracker.diagnostics(1_200_000_000L, true).blackoutMasksRealFix)
        assertNull(tracker.runtimeState(1_200_000_000L, true).runtimeFix)
    }

    @Test
    fun freshStaleHistoricalAndRuntimeMaskingSemanticsAreIndependent() {
        val tracker = GnssFreshnessTracker(freshAgeSeconds = 2.0)
        tracker.reset(1_000_000_000L)
        tracker.accept(fix(1_100_000_000L), 1_100_000_000L)

        val freshBlackout = tracker.diagnostics(1_200_000_000L, true)
        assertEquals(PhysicalGnssState.FRESH, freshBlackout.physicalFixState)
        assertEquals(RuntimeGnssAvailability.MASKED, freshBlackout.runtimeGnssAvailability)
        assertTrue(freshBlackout.hasAcquiredRealFixThisSession)
        assertTrue(freshBlackout.blackoutMasksFreshFix)

        val staleBlackout = tracker.diagnostics(4_000_000_000L, true)
        assertEquals(PhysicalGnssState.STALE, staleBlackout.physicalFixState)
        assertEquals(RuntimeGnssAvailability.MASKED, staleBlackout.runtimeGnssAvailability)
        assertTrue(staleBlackout.hasAcquiredRealFixThisSession)
        assertTrue("Legacy field is explicitly historical", staleBlackout.blackoutMasksRealFix)
        assertFalse("A historical fix is not a currently fresh masked fix", staleBlackout.blackoutMasksFreshFix)

        val restored = tracker.diagnostics(4_000_000_000L, false)
        assertEquals(RuntimeGnssAvailability.UNAVAILABLE, restored.runtimeGnssAvailability)
    }

    @Test
    fun satelliteCountsRemainNullWhenStatusIsUnavailable() {
        val tracker = GnssFreshnessTracker()
        tracker.reset(1_000_000_000L)
        assertFalse(tracker.diagnostics(1_000_000_000L, false).gnssStatusAvailable)
        assertNull(tracker.diagnostics(1_000_000_000L, false).satellitesVisible)

        tracker.setGnssStatusAvailable(true)
        assertTrue(tracker.diagnostics(1_000_000_000L, false).gnssStatusAvailable)
        assertNull(tracker.diagnostics(1_000_000_000L, false).satellitesUsedInFix)
        tracker.updateSatelliteCounts(12, 5)
        assertEquals(12, tracker.diagnostics(1_000_000_000L, false).satellitesVisible)
        assertEquals(5, tracker.diagnostics(1_000_000_000L, false).satellitesUsedInFix)
        tracker.setGnssStatusAvailable(false)
        assertNull(tracker.diagnostics(1_000_000_000L, false).satellitesVisible)
    }

    @Test
    fun freshFixBecomesStaleByMonotonicAge() {
        val tracker = GnssFreshnessTracker(freshAgeSeconds = 2.0)
        assertEquals(GnssStatus.FRESH, tracker.accept(fix(1_000_000_000L), 1_100_000_000L))
        assertTrue(tracker.runtimeState(2_000_000_000L, false).isFresh)
        val stale = tracker.runtimeState(3_100_000_001L, false)
        assertEquals(GnssStatus.STALE, stale.status)
        assertFalse(stale.isFresh)
        assertNotNull(stale.runtimeFix)
    }

    @Test
    fun blackoutReturnsNoRuntimeGnssButRetainsPhysicalFix() {
        val tracker = GnssFreshnessTracker()
        val physical = fix(1_000_000_000L)
        tracker.accept(physical, 1_000_000_000L)

        val runtime = tracker.runtimeState(1_100_000_000L, true)
        assertEquals(GnssStatus.SIMULATED_BLACKOUT, runtime.status)
        assertNull(runtime.runtimeFix)
        assertFalse(runtime.isFresh)
        assertEquals(physical, tracker.latestPhysicalFix())
        assertTrue(tracker.diagnostics(1_100_000_000L, true).blackoutMasksRealFix)
    }

    @Test
    fun invalidAndDisabledStatesAreExplicit() {
        val tracker = GnssFreshnessTracker()
        assertEquals(GnssStatus.INVALID, tracker.accept(fix(100L, 100.0), 100L))
        assertEquals(GnssStatus.INVALID, tracker.runtimeState(200L, false).status)
        tracker.setProviderEnabled(false)
        assertEquals(GnssStatus.PROVIDER_DISABLED, tracker.runtimeState(200L, false).status)
    }

    @Test
    fun newerUnchangedCallbackRemainsFresh() {
        val tracker = GnssFreshnessTracker()
        tracker.accept(fix(1_000_000_000L), 1_000_000_000L)
        assertEquals(GnssStatus.FRESH, tracker.accept(fix(2_000_000_000L), 2_000_000_000L))
        assertEquals(GnssStatus.FRESH, tracker.runtimeState(2_100_000_000L, false).status)
    }

    @Test
    fun repeatedOrOlderPhysicalTimestampIsStale() {
        val tracker = GnssFreshnessTracker()
        tracker.accept(fix(2_000_000_000L), 2_000_000_000L)
        assertEquals(GnssStatus.STALE, tracker.accept(fix(2_000_000_000L), 2_100_000_000L))
        assertEquals(GnssStatus.STALE, tracker.accept(fix(1_900_000_000L), 2_200_000_000L))
    }
}
