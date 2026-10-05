package org.sih26168.idrlogger.system

import android.os.PowerManager
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import org.sih26168.idrlogger.model.SystemHealthSnapshot

class SystemHealthMonitorTest {
    @Test fun unavailableSystemHealthValuesRemainNull() {
        val missing = SystemHealthSnapshot()
        assertNull(missing.batteryPercent)
        assertNull(missing.batteryTemperatureC)
        assertNull(missing.thermalStatus)
        assertNull(thermalStatusLabel(null))
    }

    @Test fun thermalStatusHasStableHumanReadableLabels() {
        assertEquals("NONE", thermalStatusLabel(PowerManager.THERMAL_STATUS_NONE))
        assertEquals("SEVERE", thermalStatusLabel(PowerManager.THERMAL_STATUS_SEVERE))
        assertEquals("UNKNOWN_999", thermalStatusLabel(999))
    }
}
