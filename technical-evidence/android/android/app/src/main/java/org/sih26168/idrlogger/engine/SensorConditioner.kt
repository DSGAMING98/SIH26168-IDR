package org.sih26168.idrlogger.engine

import java.util.ArrayDeque
import kotlin.math.sqrt
import org.sih26168.idrlogger.model.LiveIdrSample
import org.sih26168.idrlogger.model.Quaternion
import org.sih26168.idrlogger.model.Vector3

class SensorConditioner(
    private val filterTimeConstantS: Double = 0.30,
    private val stationaryWindowSamples: Int = 20,
) {
    private val forwardShockFilter = RobustTransientFilter(minimumLimit = 3.5)
    private val leftShockFilter = RobustTransientFilter(minimumLimit = 3.5)
    private val yawShockFilter = RobustTransientFilter(minimumLimit = 0.55)
    private val accelerationHistory = ArrayDeque<Double>()
    private val gyroHistory = ArrayDeque<Double>()
    private var filteredForward = 0.0
    private var filteredLeft = 0.0
    private var filteredYawRate = 0.0
    private var initialized = false
    private var motionState = MotionState.INITIALIZING
    private var movingEvidenceSamples = 0

    fun reset() {
        accelerationHistory.clear()
        gyroHistory.clear()
        filteredForward = 0.0
        filteredLeft = 0.0
        filteredYawRate = 0.0
        initialized = false
        motionState = MotionState.INITIALIZING
        movingEvidenceSamples = 0
        forwardShockFilter.reset()
        leftShockFilter.reset()
        yawShockFilter.reset()
    }

    fun condition(sample: LiveIdrSample, dtS: Double, vehicleYawRad: Double): ConditionedMotion {
        val acceleration = sample.accelerometer
        val gravity = sample.gravity
        val rotation = sample.rotation
        val gyroscope = sample.gyroscope
        val magnetic = sample.magnetometer
        val attitudeAvailable = acceleration != null && gravity != null && rotation != null
        val worldLinear = if (attitudeAvailable) {
            rotate(rotation!!, subtract(acceleration!!, gravity!!))
        } else {
            Vector3(0.0, 0.0, 0.0)
        }
        val sinYaw = kotlin.math.sin(vehicleYawRad)
        val cosYaw = kotlin.math.cos(vehicleYawRad)
        val rawForward = forwardShockFilter.filter(
            (worldLinear.x * sinYaw + worldLinear.y * cosYaw).coerceIn(-8.0, 8.0)
        )
        val rawLeft = leftShockFilter.filter(
            (-worldLinear.x * cosYaw + worldLinear.y * sinYaw).coerceIn(-8.0, 8.0)
        )
        val worldGyro = if (gyroscope != null && rotation != null) rotate(rotation, gyroscope) else null
        val rawYawRate = yawShockFilter.filter((-(worldGyro?.z ?: 0.0)).coerceIn(-1.5, 1.5))
        val alpha = if (!initialized) 1.0 else (dtS / (filterTimeConstantS + dtS)).coerceIn(0.0, 1.0)
        filteredForward += alpha * (rawForward - filteredForward)
        filteredLeft += alpha * (rawLeft - filteredLeft)
        filteredYawRate += alpha * (rawYawRate - filteredYawRate)
        initialized = true

        val linearMagnitude = norm(worldLinear)
        val gyroMagnitude = gyroscope?.let(::norm) ?: 0.0
        push(accelerationHistory, linearMagnitude)
        push(gyroHistory, gyroMagnitude)
        val accelRms = rms(accelerationHistory)
        val gyroRms = rms(gyroHistory)
        motionState = classifyMotion(linearMagnitude, gyroMagnitude, accelRms, gyroRms)
        return ConditionedMotion(
            forwardAccelerationMps2 = filteredForward,
            leftAccelerationMps2 = filteredLeft,
            yawRateRadps = filteredYawRate,
            deviceHeadingRad = rotation?.let(::deviceTopHeadingRad),
            gyroMagnitudeRadps = gyroMagnitude,
            gravityMagnitudeMps2 = gravity?.let(::norm) ?: Double.NaN,
            magneticMagnitudeUt = magnetic?.let(::norm) ?: Double.NaN,
            accelerationRmsMps2 = accelRms,
            gyroRmsRadps = gyroRms,
            motionState = motionState,
            attitudeAvailable = attitudeAvailable,
        )
    }

    private fun push(queue: ArrayDeque<Double>, value: Double) {
        queue.addLast(value)
        while (queue.size > stationaryWindowSamples) queue.removeFirst()
    }

    private fun classifyMotion(
        instantaneousAccelerationMps2: Double,
        instantaneousGyroRadps: Double,
        accelerationRmsMps2: Double,
        gyroRmsRadps: Double,
    ): MotionState {
        if (accelerationHistory.size < stationaryWindowSamples) {
            motionState = MotionState.INITIALIZING
            return motionState
        }
        val stationaryEvidence = accelerationRmsMps2 < STATIONARY_ENTRY_ACCEL_RMS_MPS2 &&
            gyroRmsRadps < STATIONARY_ENTRY_GYRO_RMS_RADPS
        val movingEvidence = instantaneousAccelerationMps2 > STATIONARY_EXIT_ACCEL_MPS2 ||
            instantaneousGyroRadps > STATIONARY_EXIT_GYRO_RADPS
        motionState = when (motionState) {
            MotionState.INITIALIZING -> if (stationaryEvidence) MotionState.LIKELY_STATIONARY else MotionState.MOVING
            MotionState.MOVING -> if (stationaryEvidence) MotionState.LIKELY_STATIONARY else MotionState.MOVING
            MotionState.LIKELY_STATIONARY -> {
                movingEvidenceSamples = if (movingEvidence) movingEvidenceSamples + 1 else 0
                if (movingEvidenceSamples >= STATIONARY_EXIT_SAMPLES) {
                    movingEvidenceSamples = 0
                    MotionState.MOVING
                } else {
                    MotionState.LIKELY_STATIONARY
                }
            }
        }
        return motionState
    }

    private fun rms(values: Collection<Double>): Double = if (values.isEmpty()) 0.0 else {
        sqrt(values.sumOf { it * it } / values.size)
    }

    private fun subtract(first: Vector3, second: Vector3) = Vector3(
        first.x - second.x,
        first.y - second.y,
        first.z - second.z,
    )

    private fun norm(value: Vector3): Double = sqrt(value.x * value.x + value.y * value.y + value.z * value.z)

    private fun rotate(quaternion: Quaternion, vector: Vector3): Vector3 {
        val magnitude = sqrt(
            quaternion.x * quaternion.x + quaternion.y * quaternion.y +
                quaternion.z * quaternion.z + quaternion.w * quaternion.w
        )
        if (!magnitude.isFinite() || magnitude < 1e-9) return vector
        val x = quaternion.x / magnitude
        val y = quaternion.y / magnitude
        val z = quaternion.z / magnitude
        val w = quaternion.w / magnitude
        val r00 = 1.0 - 2.0 * (y * y + z * z)
        val r01 = 2.0 * (x * y - z * w)
        val r02 = 2.0 * (x * z + y * w)
        val r10 = 2.0 * (x * y + z * w)
        val r11 = 1.0 - 2.0 * (x * x + z * z)
        val r12 = 2.0 * (y * z - x * w)
        val r20 = 2.0 * (x * z - y * w)
        val r21 = 2.0 * (y * z + x * w)
        val r22 = 1.0 - 2.0 * (x * x + y * y)
        return Vector3(
            r00 * vector.x + r01 * vector.y + r02 * vector.z,
            r10 * vector.x + r11 * vector.y + r12 * vector.z,
            r20 * vector.x + r21 * vector.y + r22 * vector.z,
        )
    }

    private fun deviceTopHeadingRad(quaternion: Quaternion): Double {
        val topInWorld = rotate(quaternion, Vector3(0.0, 1.0, 0.0))
        return kotlin.math.atan2(topInWorld.x, topInWorld.y)
    }

    companion object {
        const val STATIONARY_ENTRY_ACCEL_RMS_MPS2 = 0.35
        const val STATIONARY_ENTRY_GYRO_RMS_RADPS = 0.04
        const val STATIONARY_EXIT_ACCEL_MPS2 = 0.60
        const val STATIONARY_EXIT_GYRO_RADPS = 0.08
        const val STATIONARY_EXIT_SAMPLES = 5
    }
}

/**
 * Causal Hampel-style transient guard for isolated pothole and mount-shock impulses.
 *
 * The minimum limit deliberately preserves ordinary braking and steering. Only a sample that is
 * far outside the recent median/MAD envelope is clipped; sustained motion quickly becomes part of
 * the window and therefore remains observable by the EKF and ML features.
 */
internal class RobustTransientFilter(
    private val windowSize: Int = 9,
    private val minimumLimit: Double,
    private val madScale: Double = 6.0,
) {
    private val history = ArrayDeque<Double>()

    init {
        require(windowSize >= 3 && windowSize % 2 == 1)
        require(minimumLimit > 0.0 && madScale > 0.0)
    }

    fun reset() = history.clear()

    fun filter(value: Double): Double {
        if (!value.isFinite()) return 0.0
        if (history.size < 3) {
            push(value)
            return value
        }
        val median = history.sorted()[history.size / 2]
        val deviations = history.map { kotlin.math.abs(it - median) }.sorted()
        val mad = deviations[deviations.size / 2]
        val limit = maxOf(minimumLimit, madScale * 1.4826 * mad)
        val guarded = value.coerceIn(median - limit, median + limit)
        push(value)
        return guarded
    }

    private fun push(value: Double) {
        history.addLast(value)
        while (history.size > windowSize) history.removeFirst()
    }
}
