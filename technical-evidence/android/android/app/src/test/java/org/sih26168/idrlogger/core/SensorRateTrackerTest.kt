package org.sih26168.idrlogger.core

import org.junit.Assert.assertEquals
import org.junit.Test
import org.sih26168.idrlogger.model.SensorKind

class SensorRateTrackerTest {
    @Test
    fun reportsAchievedRatesWithoutAssumingRequestedRate() {
        val tracker = SensorRateTracker()
        for (index in 0..50) tracker.record(SensorKind.ACCELEROMETER, index * 20_000_000L)
        for (index in 0..10) tracker.recordNormalized(index * 100_000_000L)

        val rates = tracker.snapshot()
        assertEquals(50.0, rates.accelerometerHz, 1e-9)
        assertEquals(10.0, rates.normalizedHz, 1e-9)
        assertEquals(0.0, rates.gyroscopeHz, 0.0)
    }
}
