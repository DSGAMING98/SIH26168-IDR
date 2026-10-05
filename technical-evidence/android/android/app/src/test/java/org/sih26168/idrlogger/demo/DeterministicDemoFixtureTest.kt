package org.sih26168.idrlogger.demo

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.sih26168.idrlogger.engine.IdrEngine
import org.sih26168.idrlogger.engine.LocalizationMode

class DeterministicDemoFixtureTest {
    @Test
    fun demoIsExplicitlySyntheticAndExercisesGnssIdrRecovery() {
        val engine = IdrEngine()
        val modes = mutableSetOf<LocalizationMode>()
        var blackoutStartEast = 0.0
        var blackoutEndEast = 0.0
        var blackoutStartSpeed = 0.0
        var blackoutEndSpeed = 0.0
        var finalMode = LocalizationMode.WAITING_FOR_GNSS
        var finalInnovationM: Double? = null
        for (index in 0 until DeterministicDemoFixture.TOTAL_SAMPLES) {
            val frame = DeterministicDemoFixture.frame(index)
            if (index in DeterministicDemoFixture.BLACKOUT_START_SAMPLE until DeterministicDemoFixture.BLACKOUT_END_SAMPLE) {
                assertNull(frame.sample.gnss)
                assertTrue(frame.phaseLabel.contains("SYNTHETIC"))
            }
            val state = engine.process(frame.sample)
            finalMode = state.localizationMode
            finalInnovationM = state.gnssInnovationM
            modes += state.localizationMode
            if (index == DeterministicDemoFixture.BLACKOUT_START_SAMPLE) {
                blackoutStartEast = state.eastM
                blackoutStartSpeed = state.speedMps
            }
            if (index == DeterministicDemoFixture.BLACKOUT_END_SAMPLE - 1) {
                blackoutEndEast = state.eastM
                blackoutEndSpeed = state.speedMps
            }
        }
        assertTrue(LocalizationMode.GNSS_ACTIVE in modes)
        assertTrue(LocalizationMode.IDR_ACTIVE in modes)
        assertTrue(LocalizationMode.GNSS_VERIFYING in modes)
        assertTrue(LocalizationMode.GNSS_RECOVERING in modes)
        assertEquals(LocalizationMode.GNSS_ACTIVE, finalMode)
        assertTrue(
            "Blackout propagation was ${blackoutEndEast - blackoutStartEast} m; speed $blackoutStartSpeed -> $blackoutEndSpeed",
            blackoutEndEast - blackoutStartEast > 50.0,
        )
        println(
            "PHASE10_DEMO blackout_propagation_m=${blackoutEndEast - blackoutStartEast} " +
                "speed_start=$blackoutStartSpeed speed_end=$blackoutEndSpeed final_mode=$finalMode " +
                "final_innovation_m=$finalInnovationM modes=${modes.sortedBy { it.ordinal }}"
        )
        assertEquals(DeterministicDemoFixture.TOTAL_SAMPLES, engine.snapshot(true).state.sequenceId.toInt() + 1)
    }
}
