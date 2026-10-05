package org.sih26168.idrlogger.product

import org.junit.Assert.assertEquals
import org.junit.Test

class InsightsCalculatorTest {
    @Test fun aggregatesCompletedAndInterruptedTripsButNotRunning() {
        val a = TripEntity().apply { status = "COMPLETED"; distanceM = 1000.0; durationSeconds = 100.0; averageSpeedMps = 10.0; maximumSpeedMps = 14.0; gnssLossEvents = 2; idrDurationSeconds = 8.0; averageUncertaintyM = 4.0 }
        val b = TripEntity().apply { status = "INTERRUPTED"; distanceM = 500.0; durationSeconds = 100.0; averageSpeedMps = 5.0; maximumSpeedMps = 8.0; gnssLossEvents = 1; idrDurationSeconds = 2.0; averageUncertaintyM = 6.0 }
        val ignored = TripEntity().apply { status = "RUNNING"; distanceM = 99_000.0 }
        val result = InsightsCalculator.calculate(listOf(a, b, ignored))
        assertEquals(2, result.tripCount); assertEquals(1500.0, result.totalDistanceM, 0.0)
        assertEquals(7.5, result.averageSpeedMps, 0.0); assertEquals(14.0, result.maximumSpeedMps, 0.0)
        assertEquals(3, result.gnssLossEvents); assertEquals(10.0, result.totalIdrSeconds, 0.0)
        assertEquals(5.0, result.averageUncertaintyM!!, 0.0)
    }
}
