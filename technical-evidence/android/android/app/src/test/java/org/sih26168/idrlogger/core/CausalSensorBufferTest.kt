package org.sih26168.idrlogger.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.sih26168.idrlogger.model.SensorKind
import org.sih26168.idrlogger.model.TimedSensorValue

class CausalSensorBufferTest {
    private fun sample(time: Long, x: Double) = TimedSensorValue(
        SensorKind.ACCELEROMETER,
        time,
        listOf(x, 0.0, 0.0),
        3,
    )

    @Test
    fun snapshotNeverUsesFutureSample() {
        val buffer = CausalSensorBuffer()
        assertTrue(buffer.add(sample(100L, 1.0)))
        assertTrue(buffer.add(sample(300L, 3.0)))

        assertNull(buffer.latestAtOrBefore(SensorKind.ACCELEROMETER, 99L))
        assertEquals(1.0, buffer.latestAtOrBefore(SensorKind.ACCELEROMETER, 200L)!!.values[0], 0.0)
        assertEquals(3.0, buffer.latestAtOrBefore(SensorKind.ACCELEROMETER, 300L)!!.values[0], 0.0)
    }

    @Test
    fun rejectsDuplicateAndOutOfOrderSamples() {
        val buffer = CausalSensorBuffer()
        assertTrue(buffer.add(sample(200L, 2.0)))
        assertFalse(buffer.add(sample(200L, 9.0)))
        assertFalse(buffer.add(sample(100L, 1.0)))
        assertEquals(2.0, buffer.latestAtOrBefore(SensorKind.ACCELEROMETER, 300L)!!.values[0], 0.0)
    }
}
