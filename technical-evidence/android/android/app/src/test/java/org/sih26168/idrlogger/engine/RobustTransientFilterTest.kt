package org.sih26168.idrlogger.engine

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class RobustTransientFilterTest {
    @Test
    fun isolatedPotholeImpulseIsBoundedWithoutMovingTheBaseline() {
        val filter = RobustTransientFilter(minimumLimit = 3.5)
        repeat(9) { assertEquals(0.0, filter.filter(0.0), 1e-12) }

        assertEquals(3.5, filter.filter(8.0), 1e-12)
        assertEquals(0.0, filter.filter(0.0), 1e-12)
    }

    @Test
    fun ordinaryBrakingAndSustainedAccelerationRemainObservable() {
        val filter = RobustTransientFilter(minimumLimit = 3.5)
        repeat(9) { filter.filter(0.0) }

        assertEquals(-3.0, filter.filter(-3.0), 1e-12)
        val sustained = List(10) { filter.filter(4.5) }
        assertTrue(sustained.last() > 4.4)
    }

    @Test
    fun resetRemovesPreviousMotionHistory() {
        val filter = RobustTransientFilter(minimumLimit = 3.5)
        repeat(9) { filter.filter(4.0) }
        filter.reset()

        assertEquals(0.0, filter.filter(0.0), 1e-12)
    }
}
