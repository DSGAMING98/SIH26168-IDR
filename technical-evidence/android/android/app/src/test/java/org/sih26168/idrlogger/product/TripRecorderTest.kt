package org.sih26168.idrlogger.product

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.sih26168.idrlogger.engine.LocalizationMode
import org.sih26168.idrlogger.engine.NavigationState

class TripRecorderTest {
    private class FakeStore : TripStore {
        val trips = mutableListOf<TripEntity>(); val samples = mutableListOf<TripSampleEntity>()
        override fun create(trip: TripEntity): Long { trip.id = 9; trips += trip; return 9 }
        override fun addSample(sample: TripSampleEntity) { samples += sample }
        override fun update(trip: TripEntity) = Unit
        override fun markAbandonedInterrupted() = Unit
    }

    @Test fun recordsOnlyDownsampledProductSamplesAndFinalSummary() {
        val store = FakeStore(); val recorder = TripRecorder(store) { it.run() }
        recorder.start(1000L, "/session")
        recorder.record(nav(1_000_000_000L, 12.0), 1000)
        recorder.record(nav(1_500_000_000L, 12.00001), 1500)
        recorder.record(nav(2_100_000_000L, 12.0001, LocalizationMode.IDR_ACTIVE), 2100)
        recorder.stop(3000)
        assertFalse(recorder.isRecording()); assertEquals(2, store.samples.size)
        assertEquals(9, store.samples.first().tripId)
        assertEquals("COMPLETED", store.trips.single().status)
        assertTrue(store.trips.single().distanceM > 0.0)
        assertEquals(1, store.trips.single().gnssLossEvents)
    }

    private fun nav(ns: Long, lat: Double, mode: LocalizationMode = LocalizationMode.GNSS_ACTIVE) = NavigationState(
        sequenceId = ns, monotonicTimestampNs = ns, latitudeDeg = lat, longitudeDeg = 77.0,
        speedMps = 3.0, localizationMode = mode)
}
