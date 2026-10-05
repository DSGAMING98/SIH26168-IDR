package org.sih26168.idrlogger.telemetry

import org.junit.Assert.*
import org.junit.Test
import org.sih26168.idrlogger.engine.*

class TelemetryPerformanceTest {
    @Test fun observerLeavesEstimatorResultsUnchangedAndWarmProcessingExceedsTenHertz() {
        val plain = IdrEngine(); val observed = IdrEngine()
        EngineTestFixtures.calibrateMoving(plain); EngineTestFixtures.calibrateMoving(observed)
        val transport = TestTransport()
        var now = 1_000_000_000L
        val client = TelemetryClient(transport, { now }, automaticWorker = false)
        client.configure(TelemetryConfig(true, "ws://localhost/ws/telemetry"))
        val token = client.startSession(); client.pump(); transport.sockets.last().opened(); client.pump()
        val diagnostics = TelemetryDiagnostics(recording = true)
        val off = mutableListOf<Double>(); val on = mutableListOf<Double>(); val jsonTimes = mutableListOf<Double>()
        repeat(1800) { index ->
            val sample = EngineTestFixtures.sample(index + 6L, 1_600_000_000L + index * 100_000_000L, blackout = true)
            var start = System.nanoTime()
            val a = plain.process(sample)
            val offMs = (System.nanoTime() - start) / 1e6
            start = System.nanoTime()
            val b = observed.process(sample)
            client.publish(b, diagnostics, token)
            val onMs = (System.nanoTime() - start) / 1e6
            assertEquals(a.copy(engineAverageMs = 0.0, engineP95Ms = 0.0), b.copy(engineAverageMs = 0.0, engineP95Ms = 0.0))
            // Worker work, deliberately excluded from online caller latency.
            start = System.nanoTime()
            TelemetrySerializer.serialize(TelemetryMessage.fromNavigation(b, diagnostics), token, index.toLong())
            val jsonMs = (System.nanoTime() - start) / 1e6
            now += 100_000_000L; client.pump()
            if (index >= 300) { off.add(offMs); on.add(onMs); jsonTimes.add(jsonMs) }
        }
        fun report(name: String, values: List<Double>) {
            val sorted = values.sorted()
            println("COMMAND_CENTER_PERF " + name + " samples_per_second=" + 1000.0 / values.average() +
                " average_ms=" + values.average() + " p95_ms=" + sorted[(sorted.size * 0.95).toInt()] + " samples=" + values.size)
        }
        report("engine_only", off); report("engine_plus_publish", on); report("worker_projection_json", jsonTimes)
        println("COMMAND_CENTER_PERF methodology=warm_host_JVM_fake_transport_excludes_loading_maps_UI_logging_and_network_delivery")
        assertTrue(off.average() < 100); assertTrue(on.average() < 100)
        assertTrue(transport.sockets.single().messages.isNotEmpty())
        client.shutdown(); client.pump()
    }
}
