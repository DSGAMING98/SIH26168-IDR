package org.sih26168.idrlogger.product

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.sih26168.idrlogger.engine.LocalizationMode
import org.sih26168.idrlogger.engine.NavigationState
import org.sih26168.idrlogger.engine.MlRuntimeState

class TripMetricsTest {
    @Test fun computesDistanceSpeedLossAndIdrDuration() {
        val accumulator = TripMetricsAccumulator()
        accumulator.add(state(1, 12.0, 77.0, 2.0, LocalizationMode.GNSS_ACTIVE, 3.0))
        accumulator.add(state(2, 12.0001, 77.0, 4.0, LocalizationMode.IDR_ACTIVE, 5.0))
        accumulator.add(state(3, 12.0002, 77.0, 6.0, LocalizationMode.IDR_ACTIVE, 7.0))
        val result = accumulator.snapshot()
        assertTrue(result.distanceM in 21.0..23.5)
        assertEquals(5.0, result.averageSpeedMps, 1e-9)
        assertEquals(6.0, result.maximumSpeedMps, 1e-9)
        assertEquals(1, result.gnssLossEvents)
        assertEquals(0.0, result.gnssActiveDurationSeconds, 1e-9)
        assertEquals(2.0, result.idrDurationSeconds, 1e-9)
        assertEquals(2.0, result.longestIdrIntervalSeconds, 1e-9)
        assertEquals(5.0, result.averageUncertaintyM!!, 1e-9)
        assertEquals(7.0, result.maximumUncertaintyM!!, 1e-9)
    }

    @Test fun emptyMetricsAreFinite() {
        val result = TripMetricsAccumulator().snapshot()
        assertEquals(0.0, result.distanceM, 0.0); assertEquals(0.0, result.averageSpeedMps, 0.0)
    }

    @Test fun gnssActiveDurationAndGruUseAreObservedWithoutChangingEngine() {
        val accumulator = TripMetricsAccumulator()
        accumulator.add(state(1, 12.0, 77.0, 2.0, LocalizationMode.GNSS_ACTIVE, 2.0))
        accumulator.add(state(2, 12.0, 77.0, 2.0, LocalizationMode.GNSS_ACTIVE, 2.0).copy(mlState = MlRuntimeState.ML_ACCEPTED))
        val result = accumulator.snapshot()
        assertEquals(1.0, result.gnssActiveDurationSeconds, 1e-9)
        assertTrue(result.gruAssistanceUsed)
    }

    private fun state(seconds: Long, lat: Double, lon: Double, speed: Double, mode: LocalizationMode, uncertainty: Double) = NavigationState(
        sequenceId = seconds, monotonicTimestampNs = seconds * 1_000_000_000L, latitudeDeg = lat,
        longitudeDeg = lon, speedMps = speed, localizationMode = mode, horizontalUncertaintyM = uncertainty)
}
