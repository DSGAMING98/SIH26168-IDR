package org.sih26168.idrlogger.demo

import java.util.concurrent.Executors
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.TimeUnit
import org.sih26168.idrlogger.engine.IdrEngine
import org.sih26168.idrlogger.engine.NavigationSnapshot

class DemoController(private val onUpdate: (NavigationSnapshot, String, Boolean) -> Unit) {
    private val engine = IdrEngine()
    private var executor: ScheduledExecutorService? = null
    private var index = 0
    @Volatile private var paused = true
    @Volatile private var manualBlackout = false
    @Volatile private var latest = engine.snapshot(isDemoReplay = true)

    fun startOrResume() {
        if (index >= DeterministicDemoFixture.TOTAL_SAMPLES) reset()
        paused = false
        if (executor == null) {
            executor = Executors.newSingleThreadScheduledExecutor { runnable ->
                Thread(runnable, "IdrSyntheticDemo").apply { isDaemon = true }
            }.also { it.scheduleAtFixedRate(::tick, 0L, 100L, TimeUnit.MILLISECONDS) }
        }
    }

    fun pause() {
        paused = true
    }

    fun reset() {
        paused = true
        manualBlackout = false
        index = 0
        engine.reset()
        latest = engine.snapshot(isDemoReplay = true)
        onUpdate(latest, "DEMO READY — synthetic data only", false)
    }

    fun toggleManualBlackout() {
        manualBlackout = !manualBlackout
    }

    fun snapshot(): NavigationSnapshot = latest

    fun close() {
        executor?.shutdownNow()
        executor = null
    }

    private fun tick() {
        if (paused || index >= DeterministicDemoFixture.TOTAL_SAMPLES) return
        val frame = DeterministicDemoFixture.frame(index, manualBlackout)
        latest = try {
            engine.process(frame.sample)
            engine.snapshot(isDemoReplay = true)
        } catch (error: Exception) {
            engine.reportFailure(error.message ?: error.javaClass.simpleName, frame.sample.monotonicTimestampNs)
            engine.snapshot(isDemoReplay = true)
        }
        index += 1
        if (index >= DeterministicDemoFixture.TOTAL_SAMPLES) paused = true
        onUpdate(latest, frame.phaseLabel, paused)
    }
}
