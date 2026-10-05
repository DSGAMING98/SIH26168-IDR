package org.sih26168.idrlogger.engine

import org.sih26168.idrlogger.model.GnssDiagnosticsSnapshot
import org.sih26168.idrlogger.model.GnssStatus
import org.sih26168.idrlogger.model.LiveIdrSample
import org.sih26168.idrlogger.model.Quaternion
import org.sih26168.idrlogger.model.RuntimeGnssFix
import org.sih26168.idrlogger.model.SensorAvailability
import org.sih26168.idrlogger.model.Vector3
import kotlin.math.cos
import kotlin.math.sin

internal object EngineTestFixtures {
    const val ORIGIN_LAT = 12.9716
    const val ORIGIN_LON = 77.5946
    private val transform = CoordinateTransform(ORIGIN_LAT, ORIGIN_LON)
    private val availability = SensorAvailability(true, true, true, true, true, true)

    fun sample(
        sequence: Long,
        timeNs: Long,
        gnssEastM: Double? = null,
        gnssNorthM: Double = 0.0,
        gnssSpeedMps: Double = 8.0,
        gnssBearingDeg: Double = 90.0,
        blackout: Boolean = false,
        forwardAccelerationMps2: Double = 0.0,
        gyroZRadps: Double = 0.0,
        locationAgeS: Double = 0.0,
        gnssSolutionTimestampNs: Long? = null,
        rotationYawDeg: Double = 0.0,
        magnetometerDeltaUt: Double = 0.0,
        gnssAccuracyM: Double = 3.0,
    ): LiveIdrSample {
        val point = gnssEastM?.let { transform.toGeodetic(it, gnssNorthM) }
        val gnss = if (point == null || blackout) null else RuntimeGnssFix(
            latitudeDeg = point.latitudeDeg,
            longitudeDeg = point.longitudeDeg,
            altitudeM = 900.0,
            speedMps = gnssSpeedMps,
            bearingDeg = gnssBearingDeg,
            accuracyM = gnssAccuracyM,
            verticalAccuracyM = 5.0,
            speedAccuracyMps = 0.5,
            bearingAccuracyDeg = 3.0,
            provider = "gps",
        )
        val fresh = gnss != null
        return LiveIdrSample(
            sequenceId = sequence,
            elapsedSeconds = (timeNs - 1_000_000_000L) / 1e9,
            monotonicTimestampNs = timeNs,
            wallClockUtc = "2026-01-01T00:00:00Z",
            accelerometer = Vector3(forwardAccelerationMps2, 0.0, 9.80665),
            gyroscope = Vector3(0.0, 0.0, gyroZRadps),
            magnetometer = Vector3(20.0 + magnetometerDeltaUt, 30.0 - magnetometerDeltaUt, 10.0),
            gravity = Vector3(0.0, 0.0, 9.80665),
            rotation = Math.toRadians(rotationYawDeg).let { yaw ->
                Quaternion(0.0, 0.0, sin(yaw / 2.0), cos(yaw / 2.0))
            },
            gnss = gnss,
            gnssFixAgeSeconds = if (fresh) locationAgeS else null,
            gnssIsFresh = fresh,
            gnssStatus = when {
                blackout -> GnssStatus.SIMULATED_BLACKOUT
                fresh -> GnssStatus.FRESH
                else -> GnssStatus.STALE
            },
            simulatedBlackout = blackout,
            gnssDiagnostics = GnssDiagnosticsSnapshot(
                physicalCallbackCount = sequence,
                lastPhysicalGnssTimestampNs = gnssSolutionTimestampNs,
                blackoutMasksRealFix = blackout,
            ),
            availability = availability,
        )
    }

    fun calibrateMoving(engine: IdrEngine, startSequence: Long = 0L): NavigationState {
        var state = NavigationState()
        for (index in 0 until 6) {
            state = engine.process(
                sample(
                    sequence = startSequence + index,
                    timeNs = 1_000_000_000L + index * 100_000_000L,
                    gnssEastM = index * 0.8,
                )
            )
        }
        return state
    }
}
