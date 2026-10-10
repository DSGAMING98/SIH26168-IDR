package org.sih26168.idrlogger.engine

import java.util.ArrayDeque
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.tanh

internal data class FocusedSpeedPrediction(
    val directSpeedMps: Double,
    val oodExceedance: Double,
)

internal fun interface DirectSpeedPredictor {
    fun predict(rawFeatureWindow: Array<DoubleArray>): FocusedSpeedPrediction
}

/** Exact dependency-free forward pass for the validation-frozen direct-speed GRU. */
internal class FocusedVelocityModel : DirectSpeedPredictor {
    val parameterCount: Int get() = FocusedVelocityModelData.PARAMETER_COUNT
    val featureOrder: Array<String> get() = FocusedVelocityModelData.FEATURE_ORDER.copyOf()

    override fun predict(rawFeatureWindow: Array<DoubleArray>): FocusedSpeedPrediction {
        require(rawFeatureWindow.size == FocusedVelocityModelData.WINDOW_STEPS)
        require(rawFeatureWindow.all { it.size == FocusedVelocityModelData.INPUT_SIZE && it.all(Double::isFinite) })
        val normalized = Array(FocusedVelocityModelData.WINDOW_STEPS) { row ->
            DoubleArray(FocusedVelocityModelData.INPUT_SIZE) { column ->
                ((rawFeatureWindow[row][column].toFloat() - FocusedVelocityModelData.MEANS[column].toFloat()) /
                    FocusedVelocityModelData.STANDARD_DEVIATIONS[column].toFloat()).toDouble()
            }
        }
        var exceedance = 0.0
        for (row in normalized) {
            for (column in row.indices) {
                exceedance = max(
                    exceedance,
                    max(
                        FocusedVelocityModelData.NORMALIZED_LOWER_BOUNDS[column] - row[column],
                        row[column] - FocusedVelocityModelData.NORMALIZED_UPPER_BOUNDS[column],
                    ).coerceAtLeast(0.0),
                )
            }
        }

        val weights = FocusedVelocityModelData.WEIGHTS
        val inputWeightOffset = 0
        val hiddenWeightOffset = inputWeightOffset + 3 * HIDDEN * INPUT
        val inputBiasOffset = hiddenWeightOffset + 3 * HIDDEN * HIDDEN
        val hiddenBiasOffset = inputBiasOffset + 3 * HIDDEN
        val outputWeightOffset = hiddenBiasOffset + 3 * HIDDEN
        val outputBiasOffset = outputWeightOffset + HIDDEN
        var hidden = DoubleArray(HIDDEN)
        for (input in normalized) {
            val next = DoubleArray(HIDDEN)
            for (unit in 0 until HIDDEN) {
                val resetInput = affineInput(weights, inputWeightOffset, 0, unit, input) + weights[inputBiasOffset + unit]
                val updateInput = affineInput(weights, inputWeightOffset, 1, unit, input) + weights[inputBiasOffset + HIDDEN + unit]
                val newInput = affineInput(weights, inputWeightOffset, 2, unit, input) + weights[inputBiasOffset + 2 * HIDDEN + unit]
                val resetHidden = affineHidden(weights, hiddenWeightOffset, 0, unit, hidden) + weights[hiddenBiasOffset + unit]
                val updateHidden = affineHidden(weights, hiddenWeightOffset, 1, unit, hidden) + weights[hiddenBiasOffset + HIDDEN + unit]
                val newHidden = affineHidden(weights, hiddenWeightOffset, 2, unit, hidden) + weights[hiddenBiasOffset + 2 * HIDDEN + unit]
                val resetGate = sigmoid(resetInput + resetHidden)
                val updateGate = sigmoid(updateInput + updateHidden)
                val candidate = tanh(newInput + resetGate * newHidden)
                next[unit] = (1.0 - updateGate) * candidate + updateGate * hidden[unit]
            }
            hidden = next
        }
        var raw = weights[outputBiasOffset].toDouble()
        for (unit in 0 until HIDDEN) raw += weights[outputWeightOffset + unit] * hidden[unit]
        val directSpeed = FocusedVelocityModelData.MAXIMUM_DIRECT_SPEED_MPS * tanh(raw)
        check(directSpeed.isFinite() && exceedance.isFinite())
        return FocusedSpeedPrediction(directSpeed, exceedance)
    }

    private fun affineInput(weights: FloatArray, offset: Int, gate: Int, unit: Int, input: DoubleArray): Double {
        val row = gate * HIDDEN + unit
        var result = 0.0
        for (column in 0 until INPUT) result += weights[offset + row * INPUT + column] * input[column]
        return result
    }

    private fun affineHidden(weights: FloatArray, offset: Int, gate: Int, unit: Int, hidden: DoubleArray): Double {
        val row = gate * HIDDEN + unit
        var result = 0.0
        for (column in 0 until HIDDEN) result += weights[offset + row * HIDDEN + column] * hidden[column]
        return result
    }

    private fun sigmoid(value: Double): Double = when {
        value >= 0.0 -> 1.0 / (1.0 + exp(-value))
        else -> {
            val exponential = exp(value)
            exponential / (1.0 + exponential)
        }
    }

    private companion object {
        const val INPUT = 10
        const val HIDDEN = 64
    }
}

internal data class FocusedMlInference(
    val residualMps: Double,
    val oodExceedance: Double,
    val directSpeedMps: Double,
    val earlySuppressed: Boolean,
    val longFloorApplied: Boolean,
)

/**
 * Causal arbitration used by the frozen research candidate. History begins at GNSS loss;
 * neither scenario identity, future samples, nor reference positions are available here.
 */
internal class CausalFocusedVelocity(
    private val model: DirectSpeedPredictor = FocusedVelocityModel(),
) {
    private val history = ArrayDeque<DoubleArray>()
    private var samplesSeen = 0
    private var predictionCount = 0
    private var earlyState = true
    private var stationarySeen = false
    private var reconstructedSpeedFloorMps: Double? = null
    var latestInference: FocusedMlInference? = null
        private set
    var inferenceUpdated: Boolean = false
        private set
    var active: Boolean = false
        private set

    fun startBlackout(speedFloorMps: Double?) {
        reset()
        active = true
        reconstructedSpeedFloorMps = speedFloorMps?.takeIf { it.isFinite() && it >= 0.0 }
    }

    fun reset() {
        history.clear()
        samplesSeen = 0
        predictionCount = 0
        earlyState = true
        stationarySeen = false
        reconstructedSpeedFloorMps = null
        latestInference = null
        inferenceUpdated = false
        active = false
    }

    fun update(features: DoubleArray): Pair<MlRuntimeState, FocusedMlInference?> {
        inferenceUpdated = false
        if (!active || features.size != FocusedVelocityModelData.INPUT_SIZE || !features.all(Double::isFinite)) {
            latestInference = null
            return MlRuntimeState.ML_UNAVAILABLE to null
        }
        history.addLast(features.copyOf())
        while (history.size > FocusedVelocityModelData.WINDOW_STEPS) history.removeFirst()
        samplesSeen += 1
        if (history.size < FocusedVelocityModelData.WINDOW_STEPS) return MlRuntimeState.ML_WARMING to null
        if ((samplesSeen - FocusedVelocityModelData.WINDOW_STEPS) % FocusedVelocityModelData.UPDATE_STRIDE_STEPS != 0) {
            val previous = latestInference ?: return MlRuntimeState.ML_WARMING to null
            return stateFor(previous.oodExceedance) to previous
        }

        val originalWindow = history.toTypedArray()
        val classicalSpeed = originalWindow.last().last()
        val modelWindow = Array(originalWindow.size) { row ->
            originalWindow[row].copyOf().also { it[it.lastIndex] = 0.0 }
        }
        val prediction = model.predict(modelWindow)
        val signedAccelerationDeltaMps = originalWindow.sumOf { it[FORWARD_ACCEL_INDEX] } / NOMINAL_RATE_HZ
        val accelerationDeltaMps = abs(signedAccelerationDeltaMps)
        val yawDeltaDeg = abs(Math.toDegrees(originalWindow.sumOf { it[YAW_RATE_INDEX] } / NOMINAL_RATE_HZ))
        val disagreementMps = abs(prediction.directSpeedMps - classicalSpeed)
        val stationaryWindow = originalWindow.count { it[STATIONARY_INDEX] >= 0.5 }.toDouble() /
            originalWindow.size + 1e-12 >= STATIONARY_FRACTION
        if (stationaryWindow) {
            stationarySeen = true
        }

        var directSpeed = prediction.directSpeedMps
        var earlySuppressed = false
        if (earlyState) {
            earlySuppressed = accelerationDeltaMps < EARLY_ACCELERATION_DELTA_LIMIT_MPS &&
                yawDeltaDeg < EARLY_YAW_DELTA_LIMIT_DEG &&
                disagreementMps > EARLY_DISAGREEMENT_LIMIT_MPS
            if (earlySuppressed) directSpeed = classicalSpeed else earlyState = false
        }

        // A direct-speed proposal must not manufacture motion in a stationary window or oppose
        // strong integrated longitudinal evidence. These guards are causal and leave the frozen
        // network weights untouched.
        val dynamicsContradictPrediction =
            signedAccelerationDeltaMps >= DYNAMICS_CONSISTENCY_DELTA_LIMIT_MPS && directSpeed < classicalSpeed
        if (stationaryWindow) {
            directSpeed = 0.0
        } else if (dynamicsContradictPrediction) {
            directSpeed = classicalSpeed
        }

        var longFloorApplied = false
        val predictionTimeS = (FocusedVelocityModelData.WINDOW_STEPS +
            predictionCount * FocusedVelocityModelData.UPDATE_STRIDE_STEPS) / NOMINAL_RATE_HZ
        val floor = reconstructedSpeedFloorMps
        if (!earlySuppressed && floor != null && !stationarySeen &&
            predictionTimeS >= LONG_OUTAGE_TRANSITION_S && directSpeed < floor
        ) {
            directSpeed = floor
            longFloorApplied = true
        }
        predictionCount += 1
        latestInference = FocusedMlInference(
            residualMps = directSpeed - classicalSpeed,
            oodExceedance = prediction.oodExceedance,
            directSpeedMps = directSpeed,
            earlySuppressed = earlySuppressed,
            longFloorApplied = longFloorApplied,
        )
        inferenceUpdated = true
        return stateFor(prediction.oodExceedance) to latestInference
    }

    private fun stateFor(exceedance: Double): MlRuntimeState = when {
        exceedance > HARD_OOD_EXCEEDANCE -> MlRuntimeState.ML_REJECTED
        exceedance > SOFT_OOD_EXCEEDANCE -> MlRuntimeState.ML_OOD_LIMITED
        else -> MlRuntimeState.ML_ACCEPTED
    }

    companion object {
        const val MEASUREMENT_VARIANCE_MPS2 = FocusedVelocityModelData.VALIDATION_RESIDUAL_VARIANCE_MPS2 * 0.5
        const val SOFT_OOD_EXCEEDANCE = 0.5
        const val HARD_OOD_EXCEEDANCE = 3.0
        const val LONG_OUTAGE_TRANSITION_S = 45.0
        private const val NOMINAL_RATE_HZ = 10.0
        private const val EARLY_ACCELERATION_DELTA_LIMIT_MPS = 1.5
        private const val EARLY_YAW_DELTA_LIMIT_DEG = 15.0
        private const val EARLY_DISAGREEMENT_LIMIT_MPS = 3.0
        private const val DYNAMICS_CONSISTENCY_DELTA_LIMIT_MPS = 5.8
        private const val STATIONARY_FRACTION = 0.2
        private const val FORWARD_ACCEL_INDEX = 0
        private const val YAW_RATE_INDEX = 2
        private const val STATIONARY_INDEX = 8
    }
}
