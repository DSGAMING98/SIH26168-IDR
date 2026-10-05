package org.sih26168.idrlogger.service

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.sih26168.idrlogger.engine.AlignmentState
import org.sih26168.idrlogger.engine.LocalizationMode
import org.sih26168.idrlogger.engine.NavigationState

class TunnelTestGateTest {
    @Test
    fun rejectsBeforeRecordingOrFreshGnss() {
        assertFalse(TunnelTestGate.evaluate(false, false, NavigationState()).allowed)
        assertFalse(TunnelTestGate.evaluate(true, false, NavigationState()).allowed)
    }

    @Test
    fun rejectsWaitingCalibratingAndErrorStates() {
        val anchored = NavigationState(latitudeDeg = 12.0, longitudeDeg = 77.0, alignmentState = AlignmentState.READY)
        assertFalse(TunnelTestGate.evaluate(true, true, anchored.copy(localizationMode = LocalizationMode.WAITING_FOR_GNSS)).allowed)
        assertFalse(TunnelTestGate.evaluate(true, true, anchored.copy(
            localizationMode = LocalizationMode.CALIBRATING,
            alignmentState = AlignmentState.CALIBRATING,
        )).allowed)
        assertFalse(TunnelTestGate.evaluate(true, true, anchored.copy(localizationMode = LocalizationMode.ERROR)).allowed)
    }

    @Test
    fun acceptsOnlyFreshAnchoredReadyGnssActiveState() {
        val active = NavigationState(
            latitudeDeg = 12.0,
            longitudeDeg = 77.0,
            alignmentState = AlignmentState.READY,
            localizationMode = LocalizationMode.GNSS_ACTIVE,
        )
        assertTrue(TunnelTestGate.evaluate(true, true, active).allowed)
        assertFalse(TunnelTestGate.evaluate(true, false, active).allowed)
        assertFalse(TunnelTestGate.evaluate(true, true, active.copy(latitudeDeg = null)).allowed)
    }
}
