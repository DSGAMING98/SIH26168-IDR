package org.sih26168.idrlogger.engine

import kotlin.math.hypot
import kotlin.math.roundToLong
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.sih26168.idrlogger.map.NavGhostRenderer
import org.sih26168.idrlogger.map.RendererSelectionPolicy

class RuntimeTimingSafetyTest {
    @Test
    fun supportedRuntimeIntervalsPropagateNormallyAtBothBoundaries() {
        listOf(0.1, 0.5).forEach { dtS ->
            val engine = IdrEngine()
            EngineTestFixtures.calibrateMoving(engine)
            val trajectorySize = engine.snapshot().trajectory.size
            val state = engine.process(
                EngineTestFixtures.sample(
                    6,
                    1_500_000_000L + (dtS * 1e9).roundToLong(),
                    blackout = true,
                )
            )
            assertNotEquals(LocalizationMode.ERROR, state.localizationMode)
            assertTrue(!state.message.contains("timing discontinuity"))
            assertEquals(trajectorySize + 1, engine.snapshot().trajectory.size)
        }
    }

    @Test
    fun everyRequestedUnsupportedIntervalDropsRebasesAndResumes() {
        listOf(0.0, -0.1, 0.5001, 1.0, 10.0, 30.0, 76.074250594, 120.0).forEach { dtS ->
            val engine = IdrEngine()
            val before = EngineTestFixtures.calibrateMoving(engine)
            val trajectorySize = engine.snapshot().trajectory.size
            val gapTimestamp = 1_500_000_000L + (dtS * 1e9).roundToLong()
            val dropped = engine.process(
                EngineTestFixtures.sample(6, gapTimestamp, blackout = true, forwardAccelerationMps2 = 3.0)
            )
            assertNotEquals("dt=$dtS", LocalizationMode.ERROR, dropped.localizationMode)
            assertEquals("dt=$dtS east", before.eastM, dropped.eastM, 0.0)
            assertEquals("dt=$dtS north", before.northM, dropped.northM, 0.0)
            assertEquals("dt=$dtS trajectory", trajectorySize, engine.snapshot().trajectory.size)
            assertTrue("dt=$dtS message", dropped.message.contains("sample dropped"))

            val resumed = engine.process(
                EngineTestFixtures.sample(7, gapTimestamp + 100_000_000L, blackout = true)
            )
            assertNotEquals("dt=$dtS recovery", LocalizationMode.ERROR, resumed.localizationMode)
        }
    }
    @Test
    fun physicalSeventySixSecondGapIsDroppedAndNormalProcessingResumes() {
        val engine = IdrEngine()
        val before = EngineTestFixtures.calibrateMoving(engine)
        val trajectorySize = engine.snapshot().trajectory.size
        val gapTimestamp = 1_500_000_000L + 76_074_250_594L

        val dropped = engine.process(
            EngineTestFixtures.sample(6, gapTimestamp, blackout = true, forwardAccelerationMps2 = 2.0)
        )

        assertNotEquals(LocalizationMode.ERROR, dropped.localizationMode)
        assertEquals(LocalizationMode.GNSS_DEGRADED, dropped.localizationMode)
        assertEquals(before.eastM, dropped.eastM, 0.0)
        assertEquals(before.northM, dropped.northM, 0.0)
        assertEquals(trajectorySize, engine.snapshot().trajectory.size)
        assertTrue(dropped.message.contains("76.074 s"))
        assertTrue(dropped.message.contains("sample dropped"))

        val resumed = engine.process(
            EngineTestFixtures.sample(7, gapTimestamp + 100_000_000L, blackout = true)
        )
        assertEquals(LocalizationMode.IDR_ACTIVE, resumed.localizationMode)
        assertTrue(hypot(resumed.eastM - before.eastM, resumed.northM - before.northM) < 5.0)
    }

    @Test
    fun duplicateBackwardAndSlightlyOversizedStepsRebaselineWithoutPropagation() {
        val engine = IdrEngine()
        val anchored = EngineTestFixtures.calibrateMoving(engine)
        var baseline = 1_500_000_000L
        listOf(
            baseline to 0.0,
            baseline - 50_000_000L to -0.05,
            baseline + 460_000_000L to 0.51,
        ).forEachIndexed { index, (timestamp, expectedDt) ->
            val dropped = engine.process(
                EngineTestFixtures.sample(10L + index, timestamp, blackout = true, forwardAccelerationMps2 = 3.0)
            )
            assertNotEquals(LocalizationMode.ERROR, dropped.localizationMode)
            assertEquals(anchored.eastM, dropped.eastM, 0.0)
            assertTrue(dropped.message.contains("${"%.3f".format(java.util.Locale.US, expectedDt)} s"))
            baseline = timestamp
        }

        val resumed = engine.process(EngineTestFixtures.sample(20, baseline + 100_000_000L, blackout = true))
        assertNotEquals(LocalizationMode.ERROR, resumed.localizationMode)
    }

    @Test
    fun resetCreatesCleanBaselineAfterLongStoppedSession() {
        listOf(30L, 90L).forEach { stoppedSeconds ->
            val engine = IdrEngine()
            EngineTestFixtures.calibrateMoving(engine)
            engine.reset()
            val restarted = engine.process(
                EngineTestFixtures.sample(0, stoppedSeconds * 1_000_000_000L, gnssEastM = 0.0, gnssSpeedMps = 0.0)
            )
            assertEquals(LocalizationMode.CALIBRATING, restarted.localizationMode)
            assertTrue(!restarted.message.contains("discontinuity"))
        }
    }

    @Test
    fun multiSecondPauseDropsOnlyTheGapSample() {
        val engine = IdrEngine()
        EngineTestFixtures.calibrateMoving(engine)
        val gap = engine.process(EngineTestFixtures.sample(6, 11_500_000_000L, blackout = true))
        assertEquals(LocalizationMode.GNSS_DEGRADED, gap.localizationMode)

        val resumed = engine.process(EngineTestFixtures.sample(7, 11_600_000_000L, blackout = true))
        assertEquals(LocalizationMode.IDR_ACTIVE, resumed.localizationMode)
    }

    @Test
    fun rendererSelectionCannotInjectOrAdvanceEngineTime() {
        val engine = IdrEngine()
        EngineTestFixtures.calibrateMoving(engine)
        val policy = RendererSelectionPolicy()
        policy.select(NavGhostRenderer.MAPLIBRE_3D)
        policy.select(NavGhostRenderer.GOOGLE_3D)

        val resumed = engine.process(EngineTestFixtures.sample(6, 1_600_000_000L, blackout = true))
        assertNotEquals(LocalizationMode.ERROR, resumed.localizationMode)
        assertTrue(!resumed.message.contains("timing discontinuity"))
    }
}
