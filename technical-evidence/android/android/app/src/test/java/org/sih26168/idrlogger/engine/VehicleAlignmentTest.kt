package org.sih26168.idrlogger.engine

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class VehicleAlignmentTest {
    @Test
    fun alignmentWaitsForMotionAndLearnsDeviceToVehicleYawOffset() {
        val alignment = VehicleAlignment()
        repeat(10) { alignment.update(0.0, 90.0, 0.0) }
        assertEquals(AlignmentState.CALIBRATING, alignment.state)
        assertNull(alignment.yawOffsetRad)
        repeat(5) { alignment.update(0.0, 90.0, 8.0) }
        assertEquals(AlignmentState.READY, alignment.state)
        assertEquals(Math.PI / 2.0, alignment.yawOffsetRad!!, 1e-12)
    }
}
