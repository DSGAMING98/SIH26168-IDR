package org.sih26168.idrlogger.engine

import org.junit.Assert.assertEquals
import org.junit.Test

class CoordinateTransformTest {
    @Test
    fun localRoundTripIsStableAtPrototypeDistance() {
        val transform = CoordinateTransform(12.9716, 77.5946)
        val geodetic = transform.toGeodetic(1_250.0, -830.0)
        val local = transform.toLocal(geodetic.latitudeDeg, geodetic.longitudeDeg)
        assertEquals(1_250.0, local.eastM, 1e-6)
        assertEquals(-830.0, local.northM, 1e-6)
    }
}
