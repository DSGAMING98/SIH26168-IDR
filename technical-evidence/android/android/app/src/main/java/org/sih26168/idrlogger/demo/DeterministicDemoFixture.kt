package org.sih26168.idrlogger.demo

import org.sih26168.idrlogger.engine.CoordinateTransform
import org.sih26168.idrlogger.model.GnssDiagnosticsSnapshot
import org.sih26168.idrlogger.model.GnssStatus
import org.sih26168.idrlogger.model.LiveIdrSample
import org.sih26168.idrlogger.model.Quaternion
import org.sih26168.idrlogger.model.RuntimeGnssFix
import org.sih26168.idrlogger.model.SensorAvailability
import org.sih26168.idrlogger.model.Vector3

data class DemoFrame(
    val sample: LiveIdrSample,
    val phaseLabel: String,
)

/** Wholly synthetic, route-free judge fixture. The engine sees only its generated runtime samples. */
object DeterministicDemoFixture {
    const val TOTAL_SAMPLES = 270
    const val BLACKOUT_START_SAMPLE = 60
    const val BLACKOUT_END_SAMPLE = 160
    private const val START_NS = 10_000_000_000L
    private const val SAMPLE_PERIOD_NS = 100_000_000L
    private const val SPEED_MPS = 8.0
    private val transform = CoordinateTransform(12.9716, 77.5946)
    private val availability = SensorAvailability(true, true, true, true, true, true)

    fun frame(index: Int, manualBlackout: Boolean = false): DemoFrame {
        require(index in 0 until TOTAL_SAMPLES)
        val automaticBlackout = index in BLACKOUT_START_SAMPLE until BLACKOUT_END_SAMPLE
        val blackout = automaticBlackout || manualBlackout
        val timestampNs = START_NS + index * SAMPLE_PERIOD_NS
        val fixIndex = index - index % 5
        val fixEast = fixIndex * SPEED_MPS / 10.0
        val point = transform.toGeodetic(fixEast, 0.0)
        val gnss = if (blackout) null else RuntimeGnssFix(
            latitudeDeg = point.latitudeDeg,
            longitudeDeg = point.longitudeDeg,
            altitudeM = 900.0,
            speedMps = SPEED_MPS,
            bearingDeg = 90.0,
            accuracyM = 3.0,
            verticalAccuracyM = 5.0,
            speedAccuracyMps = 0.5,
            bearingAccuracyDeg = 3.0,
            provider = "synthetic_demo_gps",
        )
        val sample = LiveIdrSample(
            sequenceId = index.toLong(),
            elapsedSeconds = index / 10.0,
            monotonicTimestampNs = timestampNs,
            wallClockUtc = "SYNTHETIC_DEMO_T+${"%.1f".format(java.util.Locale.US, index / 10.0)}s",
            accelerometer = Vector3(if (blackout) 0.12 else 0.0, 0.0, 9.80665),
            gyroscope = Vector3(0.0, 0.0, 0.0),
            magnetometer = Vector3(20.0, 30.0, 10.0),
            gravity = Vector3(0.0, 0.0, 9.80665),
            rotation = Quaternion(0.0, 0.0, 0.0, 1.0),
            gnss = gnss,
            gnssFixAgeSeconds = if (gnss == null) null else (index - fixIndex) / 10.0,
            gnssIsFresh = gnss != null,
            gnssStatus = if (blackout) GnssStatus.SIMULATED_BLACKOUT else GnssStatus.FRESH,
            simulatedBlackout = blackout,
            gnssDiagnostics = GnssDiagnosticsSnapshot(
                physicalCallbackCount = (fixIndex / 5 + 1).toLong(),
                blackoutMasksRealFix = blackout,
            ),
            availability = availability,
        )
        val phase = when {
            manualBlackout -> "MANUAL SYNTHETIC GNSS LOSS"
            index < BLACKOUT_START_SAMPLE -> "SYNTHETIC GNSS ACTIVE"
            index < BLACKOUT_END_SAMPLE -> "SYNTHETIC GNSS LOSS"
            else -> "SYNTHETIC GNSS REACQUISITION"
        }
        return DemoFrame(sample, phase)
    }
}
