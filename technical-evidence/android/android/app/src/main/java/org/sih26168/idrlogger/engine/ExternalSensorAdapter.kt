package org.sih26168.idrlogger.engine

import org.sih26168.idrlogger.model.*

/** SI units; common monotonic clock; device axes and device-to-ENU quaternion.
 * This is an in-process/replay contract, not a physical FOG driver.
 */
data class InertialInput(
    val timestampNs: Long,
    val accelerationMps2: Vector3,
    val angularRateRadps: Vector3,
    val magneticUt: Vector3? = null,
    val gravityMps2: Vector3? = null,
    val deviceToEnu: Quaternion? = null,
)

data class ExternalGnssInput(val timestampNs: Long, val fix: RuntimeGnssFix)

fun interface NavigationInputSink {
    fun accept(sample: LiveIdrSample): NavigationState
}

/** Android already synchronizes at 10 Hz; preserve its exact masking/diagnostics. */
class AndroidNavigationAdapter(private val sink: NavigationInputSink) {
    fun accept(sample: LiveIdrSample): NavigationState = sink.accept(sample)
}

/** Causal latest-sample normalization to the frozen model's 10 Hz time base.
 * Accepts high-rate input, but does NOT claim 200 Hz estimator/model updates.
 * Missing attitude stays missing; the engine's calibration hold remains active.
 * Call from one producer thread. No interpolation, future fixes or hidden GNSS.
 */
class ExternalSensorAdapter(private val sink: NavigationInputSink) {
    private var lastInputNs = 0L
    private var lastOutputNs: Long? = null
    private var originNs: Long? = null
    private var sequence = 0L

    fun accept(input: InertialInput, gnss: ExternalGnssInput? = null,
               blackout: Boolean = false): NavigationState? {
        require(input.timestampNs > lastInputNs) { "IMU timestamps must increase and be positive" }
        fun finite(v: Vector3?) = v == null || (v.x.isFinite() && v.y.isFinite() && v.z.isFinite())
        require(finite(input.accelerationMps2) && finite(input.angularRateRadps) &&
            finite(input.magneticUt) && finite(input.gravityMps2)) { "Non-finite sensor input" }
        input.deviceToEnu?.let {
            val norm = it.x*it.x + it.y*it.y + it.z*it.z + it.w*it.w
            require(norm.isFinite() && kotlin.math.abs(norm-1.0) < 0.01) { "Quaternion must be normalized" }
        }
        require(gnss == null || gnss.timestampNs in 1..input.timestampNs) { "GNSS must not be from the future" }
        lastInputNs = input.timestampNs
        if (originNs == null) originNs = input.timestampNs
        if (lastOutputNs != null && input.timestampNs-lastOutputNs!! < 100_000_000L) return null
        lastOutputNs = input.timestampNs
        val age = gnss?.let { (input.timestampNs-it.timestampNs)/1e9 }
        val fresh = !blackout && gnss != null && age != null && age <= 3.0
        return sink.accept(LiveIdrSample(
            sequenceId = sequence++, elapsedSeconds = (input.timestampNs-originNs!!)/1e9,
            monotonicTimestampNs = input.timestampNs, wallClockUtc = "",
            accelerometer = input.accelerationMps2, gyroscope = input.angularRateRadps,
            magnetometer = input.magneticUt, gravity = input.gravityMps2, rotation = input.deviceToEnu,
            gnss = if (fresh) gnss?.fix else null, gnssFixAgeSeconds = if (fresh) age else null,
            gnssIsFresh = fresh, gnssStatus = when {
                blackout -> GnssStatus.SIMULATED_BLACKOUT
                fresh -> GnssStatus.FRESH
                else -> GnssStatus.STALE
            }, simulatedBlackout = blackout,
            gnssDiagnostics = GnssDiagnosticsSnapshot(
                lastPhysicalGnssTimestampNs = if (fresh) gnss?.timestampNs else null),
            availability = SensorAvailability(true, true, input.magneticUt != null,
                input.gravityMps2 != null, input.deviceToEnu != null, gnss != null),
        ))
    }
}
