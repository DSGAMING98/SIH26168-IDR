package org.sih26168.idrlogger.demo

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PublicBenchmarkFixtureTest {
    @Test fun publicReplayIsCompactDeterministicAndHonestlyLabelledByMetrics() {
        val replay = PublicBenchmarkFixture.replay
        assertEquals(31, replay.reference.size)
        assertEquals(replay.reference.size, replay.rawDr.size)
        assertEquals(replay.reference.size, replay.intelligentIdr.size)
        assertEquals("S1_60_STOP_GO", replay.metrics.scenarioId)
        assertEquals(60.0, replay.metrics.durationSeconds, 0.0)
        assertEquals(262.7939441749739, replay.metrics.referenceDistanceM, 1e-9)
        assertEquals(327.1854981423306, replay.metrics.rawFinalErrorM, 1e-9)
        assertEquals(74.19228462027947, replay.metrics.intelligentFinalErrorM, 1e-9)
        assertTrue(replay.metrics.intelligentFinalErrorM < replay.metrics.rawFinalErrorM)
    }

    @Test fun publicReferenceIsEvaluatorOnlyAndNotAnEngineInputFixture() {
        val publicProperties = PublicBenchmarkReplay::class.java.declaredFields.map { it.name }.toSet()
        assertTrue("reference" in publicProperties)
        assertTrue(PublicBenchmarkFixture::class.java.declaredMethods.none { it.parameterTypes.any { type -> type.name.contains("IdrEngine") } })
    }
}
