package org.sih26168.idrlogger.engine

import org.junit.Assert.assertTrue
import org.junit.Test

class EnginePerformanceTest {
    @Test
    fun warmEngineComfortablyExceedsTenHertz() {
        val engine = IdrEngine()
        EngineTestFixtures.calibrateMoving(engine)
        val timings = DoubleArray(1_000)
        for (index in timings.indices) {
            val sequence = index + 6L
            val timestamp = 1_600_000_000L + index * 100_000_000L
            val started = System.nanoTime()
            engine.process(EngineTestFixtures.sample(sequence, timestamp, blackout = true))
            timings[index] = (System.nanoTime() - started) / 1e6
        }
        val sorted = timings.sorted()
        val average = timings.average()
        val p95 = sorted[(sorted.size * 0.95).toInt().coerceAtMost(sorted.lastIndex)]
        val samplesPerSecond = 1_000.0 / average
        println("PHASE10_ENGINE_PERF samples_per_second=$samplesPerSecond average_ms=$average p95_ms=$p95")
        assertTrue("Engine must exceed 10 Hz", average < 100.0)
    }
}
