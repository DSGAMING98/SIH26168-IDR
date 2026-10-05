package org.sih26168.idrlogger.engine

import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.sin
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.sih26168.idrlogger.model.GnssDiagnosticsSnapshot
import org.sih26168.idrlogger.model.GnssStatus
import org.sih26168.idrlogger.model.LiveIdrSample
import org.sih26168.idrlogger.model.Quaternion
import org.sih26168.idrlogger.model.RuntimeGnssFix
import org.sih26168.idrlogger.model.SensorAvailability
import org.sih26168.idrlogger.model.Vector3

class PublicDatasetRegressionTest {
    @Test fun ioVnbdS1RuntimeBlackoutDoesNotUseSeparatedVboxReference() {
        val runtimeRows = rows("phase11_io_vnbd_s1_runtime.csv")
        // The committed public fixture is intentionally down-sampled to 2 Hz.
        val engine = IdrEngine(IdrEngineConfig(maximumDtS = 0.51))
        val outputs = mutableListOf<NavigationState>()
        runtimeRows.forEachIndexed { index, row ->
            // Source timestamps vary by a millisecond; the compact 2 Hz test stream is normalized exactly.
            val elapsed = index * 0.5
            val blackout = index >= 5
            val yaw = Math.toRadians(row[10])
            val gnss = if (blackout) null else RuntimeGnssFix(row[11], row[12], null, row[13], row[14], 8.0, null, null, null, "public_io_vnbd")
            val sample = LiveIdrSample(
                sequenceId = index.toLong(), elapsedSeconds = elapsed,
                monotonicTimestampNs = 1_000_000_000L + (elapsed * 1e9).toLong(), wallClockUtc = "PUBLIC_FIXTURE",
                accelerometer = Vector3(row[1], row[2], row[3]), gyroscope = Vector3(row[4], row[5], row[6]),
                magnetometer = Vector3(row[7], row[8], row[9]), gravity = Vector3(0.0, 0.0, 9.8066),
                rotation = Quaternion(0.0, 0.0, -sin(yaw / 2.0), cos(yaw / 2.0)), gnss = gnss,
                gnssFixAgeSeconds = if (blackout) null else elapsed,
                gnssIsFresh = !blackout, gnssStatus = if (blackout) GnssStatus.SIMULATED_BLACKOUT else GnssStatus.FRESH,
                simulatedBlackout = blackout,
                gnssDiagnostics = GnssDiagnosticsSnapshot(lastPhysicalGnssTimestampNs = 1_000_000_000L),
                availability = SensorAvailability(true, true, true, true, true, true),
            )
            if (blackout) assertNull(sample.gnss)
            outputs += engine.process(sample)
        }
        val final = outputs.last()
        assertEquals(LocalizationMode.CALIBRATION_REQUIRED, final.localizationMode)
        assertTrue(final.eastM.isFinite() && final.northM.isFinite())
        assertTrue("Unaligned public-data blackout must hold position", abs(final.eastM) + abs(final.northM) < 1.0)

        // Evaluator reference is deliberately opened only after all engine output exists.
        val referenceRows = rows("phase11_io_vnbd_s1_reference.csv")
        assertEquals(runtimeRows.size, referenceRows.size)
        val reference = CoordinateTransform(referenceRows.first()[1], referenceRows.first()[2])
            .toLocal(referenceRows.last()[1], referenceRows.last()[2])
        val evaluatorOnlyFinalErrorM = kotlin.math.hypot(final.eastM - reference.eastM, final.northM - reference.northM)
        assertTrue(evaluatorOnlyFinalErrorM.isFinite())
        println("PHASE11_PUBLIC_IOVNBD samples=${outputs.size} final_mode=${final.localizationMode} evaluator_only_error_m=$evaluatorOnlyFinalErrorM")
    }

    private fun rows(resource: String): List<DoubleArray> = requireNotNull(javaClass.classLoader?.getResourceAsStream(resource))
        .bufferedReader().useLines { lines -> lines.drop(1).filter { it.isNotBlank() }.map { line -> line.split(',').map(String::toDouble).toDoubleArray() }.toList() }
}
