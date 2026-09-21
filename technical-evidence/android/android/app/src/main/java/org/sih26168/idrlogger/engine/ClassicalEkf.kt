package org.sih26168.idrlogger.engine

import kotlin.math.cos
import kotlin.math.max
import kotlin.math.sin
import kotlin.math.sqrt

/** Six-state causal vehicle EKF: east, north, speed, clockwise yaw, accel bias, gyro bias. */
class ClassicalEkf {
    private val x = DoubleArray(STATE_SIZE)
    private var covariance = Array(STATE_SIZE) { DoubleArray(STATE_SIZE) }
    var initialized: Boolean = false
        private set

    val eastM: Double get() = x[EAST]
    val northM: Double get() = x[NORTH]
    val speedMps: Double get() = x[SPEED]
    val yawRad: Double get() = x[YAW]
    val accelerationBiasMps2: Double get() = x[ACCEL_BIAS]
    val gyroBiasRadps: Double get() = x[GYRO_BIAS]
    val horizontalSigmaM: Double get() = sqrt(max(covariance[EAST][EAST], covariance[NORTH][NORTH]).coerceAtLeast(1e-9))

    fun reset() {
        x.fill(0.0)
        covariance = Array(STATE_SIZE) { DoubleArray(STATE_SIZE) }
        initialized = false
    }

    fun initialize(speedMps: Double, yawRad: Double, positionSigmaM: Double) {
        reset()
        x[SPEED] = max(0.0, speedMps)
        x[YAW] = wrapAngleRad(yawRad)
        val sigmas = doubleArrayOf(positionSigmaM, positionSigmaM, 2.0, Math.toRadians(15.0), 0.25, 0.03)
        for (index in 0 until STATE_SIZE) covariance[index][index] = sigmas[index] * sigmas[index]
        initialized = true
    }

    fun predict(dtS: Double, measuredForwardAccelerationMps2: Double, measuredYawRateRadps: Double) {
        require(initialized)
        require(dtS.isFinite() && dtS > 0.0 && dtS <= MAXIMUM_DT_S)
        val acceleration = (measuredForwardAccelerationMps2 - x[ACCEL_BIAS]).coerceIn(-8.0, 8.0)
        val yawRate = (measuredYawRateRadps - x[GYRO_BIAS]).coerceIn(-1.5, 1.5)
        val oldSpeed = x[SPEED]
        x[YAW] = wrapAngleRad(x[YAW] + yawRate * dtS)
        x[SPEED] = max(0.0, oldSpeed + acceleration * dtS)
        val averageSpeed = 0.5 * (oldSpeed + x[SPEED])
        val sinYaw = sin(x[YAW])
        val cosYaw = cos(x[YAW])
        x[EAST] += averageSpeed * sinYaw * dtS
        x[NORTH] += averageSpeed * cosYaw * dtS

        val f = identity()
        f[EAST][SPEED] = sinYaw * dtS
        f[EAST][YAW] = averageSpeed * cosYaw * dtS
        f[EAST][ACCEL_BIAS] = -0.5 * sinYaw * dtS * dtS
        f[EAST][GYRO_BIAS] = -0.5 * averageSpeed * cosYaw * dtS * dtS
        f[NORTH][SPEED] = cosYaw * dtS
        f[NORTH][YAW] = -averageSpeed * sinYaw * dtS
        f[NORTH][ACCEL_BIAS] = -0.5 * cosYaw * dtS * dtS
        f[NORTH][GYRO_BIAS] = 0.5 * averageSpeed * sinYaw * dtS * dtS
        f[SPEED][ACCEL_BIAS] = -dtS
        f[YAW][GYRO_BIAS] = -dtS
        covariance = multiply(multiply(f, covariance), transpose(f))
        val accelerationVariance = 0.8 * 0.8
        val yawRateVariance = 0.08 * 0.08
        covariance[EAST][EAST] += 0.25 * accelerationVariance * dtS * dtS * dtS * dtS
        covariance[NORTH][NORTH] += 0.25 * accelerationVariance * dtS * dtS * dtS * dtS
        covariance[SPEED][SPEED] += accelerationVariance * dtS * dtS
        covariance[YAW][YAW] += yawRateVariance * dtS * dtS
        covariance[ACCEL_BIAS][ACCEL_BIAS] += 0.015 * 0.015 * dtS
        covariance[GYRO_BIAS][GYRO_BIAS] += 0.0015 * 0.0015 * dtS
        stabilize()
    }

    fun updatePosition(eastM: Double, northM: Double, accuracyM: Double) {
        val variance = accuracyM.coerceAtLeast(3.0).let { it * it }
        scalarUpdate(EAST, eastM - x[EAST], variance)
        scalarUpdate(NORTH, northM - x[NORTH], variance)
    }

    fun updateSpeed(speedMps: Double, standardDeviationMps: Double = 1.5) {
        if (speedMps.isFinite() && speedMps >= 0.0) {
            scalarUpdate(SPEED, speedMps - x[SPEED], standardDeviationMps * standardDeviationMps)
            if (x[SPEED] < 0.0) x[SPEED] = 0.0
        }
    }

    fun updateYaw(yawRad: Double, standardDeviationRad: Double = Math.toRadians(15.0)) {
        if (yawRad.isFinite()) scalarUpdate(YAW, wrapAngleRad(yawRad - x[YAW]), standardDeviationRad * standardDeviationRad)
        x[YAW] = wrapAngleRad(x[YAW])
    }

    fun applyStationaryConstraint() {
        scalarUpdate(SPEED, -x[SPEED], 0.25 * 0.25)
        if (x[SPEED] < 0.05) x[SPEED] = 0.0
    }

    /** Hard physical safety envelope for an uncorrected speed state; never invents acceleration. */
    fun constrainSpeed(maximumSpeedMps: Double) {
        require(maximumSpeedMps.isFinite() && maximumSpeedMps >= 0.0)
        if (x[SPEED] > maximumSpeedMps) {
            x[SPEED] = maximumSpeedMps
            covariance[SPEED][SPEED] = max(covariance[SPEED][SPEED], 4.0)
            stabilize()
        }
    }

    /** Hold position when vehicle yaw is unknown while growing uncertainty honestly. */
    fun holdForMissingAlignment(dtS: Double) {
        require(initialized)
        require(dtS.isFinite() && dtS > 0.0 && dtS <= MAXIMUM_DT_S)
        x[SPEED] = 0.0
        covariance[SPEED][SPEED] = max(covariance[SPEED][SPEED], 4.0)
        val positionVarianceGrowth = UNKNOWN_DIRECTION_SPEED_SIGMA_MPS * UNKNOWN_DIRECTION_SPEED_SIGMA_MPS * dtS
        covariance[EAST][EAST] += positionVarianceGrowth
        covariance[NORTH][NORTH] += positionVarianceGrowth
        covariance[YAW][YAW] += Math.toRadians(8.0).let { it * it } * dtS
        covariance[ACCEL_BIAS][ACCEL_BIAS] += 0.02 * 0.02 * dtS
        covariance[GYRO_BIAS][GYRO_BIAS] += 0.002 * 0.002 * dtS
        stabilize()
    }

    fun applyMlSpeedMeasurement(targetSpeedMps: Double, varianceMps2: Double) {
        if (targetSpeedMps.isFinite()) {
            scalarUpdate(SPEED, max(0.0, targetSpeedMps) - x[SPEED], varianceMps2.coerceAtLeast(0.25))
            x[SPEED] = max(0.0, x[SPEED])
        }
    }

    fun innovationTo(eastM: Double, northM: Double): Double = kotlin.math.hypot(eastM - x[EAST], northM - x[NORTH])

    fun nudgePositionToward(eastM: Double, northM: Double, maximumStepM: Double): Double {
        val dx = eastM - x[EAST]
        val dy = northM - x[NORTH]
        val distance = kotlin.math.hypot(dx, dy)
        if (distance <= 1e-12) return 0.0
        val step = minOf(distance, maximumStepM.coerceAtLeast(0.0))
        x[EAST] += dx / distance * step
        x[NORTH] += dy / distance * step
        return step
    }

    fun isFinite(): Boolean = x.all(Double::isFinite) && covariance.all { row -> row.all(Double::isFinite) }

    private fun scalarUpdate(index: Int, residual: Double, measurementVariance: Double) {
        val innovationVariance = covariance[index][index] + measurementVariance.coerceAtLeast(1e-9)
        if (!innovationVariance.isFinite() || innovationVariance <= 0.0) return
        val gain = DoubleArray(STATE_SIZE) { covariance[it][index] / innovationVariance }
        for (row in 0 until STATE_SIZE) x[row] += gain[row] * residual
        val old = covariance
        val updated = Array(STATE_SIZE) { DoubleArray(STATE_SIZE) }
        for (row in 0 until STATE_SIZE) {
            for (column in 0 until STATE_SIZE) {
                updated[row][column] = old[row][column] - gain[row] * old[index][column]
            }
        }
        covariance = updated
        stabilize()
    }

    private fun stabilize() {
        for (row in 0 until STATE_SIZE) {
            for (column in row + 1 until STATE_SIZE) {
                val symmetric = 0.5 * (covariance[row][column] + covariance[column][row])
                covariance[row][column] = symmetric
                covariance[column][row] = symmetric
            }
            covariance[row][row] = covariance[row][row].coerceAtLeast(1e-9)
        }
    }

    private fun identity() = Array(STATE_SIZE) { row -> DoubleArray(STATE_SIZE) { column -> if (row == column) 1.0 else 0.0 } }

    private fun transpose(matrix: Array<DoubleArray>) = Array(STATE_SIZE) { row -> DoubleArray(STATE_SIZE) { column -> matrix[column][row] } }

    private fun multiply(first: Array<DoubleArray>, second: Array<DoubleArray>): Array<DoubleArray> {
        return Array(STATE_SIZE) { row ->
            DoubleArray(STATE_SIZE) { column ->
                var value = 0.0
                for (inner in 0 until STATE_SIZE) value += first[row][inner] * second[inner][column]
                value
            }
        }
    }

    companion object {
        const val MAXIMUM_DT_S = 0.5
        private const val STATE_SIZE = 6
        private const val EAST = 0
        private const val NORTH = 1
        private const val SPEED = 2
        private const val YAW = 3
        private const val ACCEL_BIAS = 4
        private const val GYRO_BIAS = 5
        private const val UNKNOWN_DIRECTION_SPEED_SIGMA_MPS = 5.0
    }
}
