package org.sih26168.idrlogger.engine

import java.util.ArrayDeque
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.tanh

data class MlInference(
    val residualMps: Double,
    val oodExceedance: Double,
)

/** Exact dependency-free forward pass for the frozen PyTorch one-layer GRU. */
class FrozenVelocityModel {
    val parameterCount: Int get() = FrozenVelocityModelData.PARAMETER_COUNT
    val featureOrder: Array<String> get() = FrozenVelocityModelData.FEATURE_ORDER.copyOf()

    fun predict(rawFeatureWindow: Array<DoubleArray>): MlInference {
        require(rawFeatureWindow.size == FrozenVelocityModelData.WINDOW_STEPS)
        require(rawFeatureWindow.all { it.size == FrozenVelocityModelData.INPUT_SIZE && it.all(Double::isFinite) })
        val normalized = Array(FrozenVelocityModelData.WINDOW_STEPS) { row ->
            DoubleArray(FrozenVelocityModelData.INPUT_SIZE) { column ->
                ((rawFeatureWindow[row][column].toFloat() - FrozenVelocityModelData.MEANS[column].toFloat()) /
                    FrozenVelocityModelData.STANDARD_DEVIATIONS[column].toFloat()).toDouble()
            }
        }
        var exceedance = 0.0
        for (row in normalized) {
            for (column in row.indices) {
                exceedance = max(
                    exceedance,
                    max(
                        FrozenVelocityModelData.NORMALIZED_LOWER_BOUNDS[column] - row[column],
                        row[column] - FrozenVelocityModelData.NORMALIZED_UPPER_BOUNDS[column],
                    ).coerceAtLeast(0.0),
                )
            }
        }
        val weights = FrozenVelocityModelData.WEIGHTS
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
        val residual = FrozenVelocityModelData.MAXIMUM_RESIDUAL_MPS * tanh(raw)
        check(residual.isFinite() && exceedance.isFinite())
        return MlInference(residual, exceedance)
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

    companion object {
        private const val INPUT = 10
        private const val HIDDEN = 32
    }
}

class CausalMlVelocity(private val model: FrozenVelocityModel = FrozenVelocityModel()) {
    private val history = ArrayDeque<DoubleArray>()
    private var samplesSeen = 0
    var latestInference: MlInference? = null
        private set
    var inferenceUpdated: Boolean = false
        private set

    fun reset() {
        history.clear()
        samplesSeen = 0
        latestInference = null
        inferenceUpdated = false
    }

    fun update(features: DoubleArray): Pair<MlRuntimeState, MlInference?> {
        inferenceUpdated = false
        if (features.size != FrozenVelocityModelData.INPUT_SIZE || !features.all(Double::isFinite)) {
            latestInference = null
            return MlRuntimeState.ML_UNAVAILABLE to null
        }
        history.addLast(features.copyOf())
        while (history.size > FrozenVelocityModelData.WINDOW_STEPS) history.removeFirst()
        samplesSeen += 1
        if (history.size < FrozenVelocityModelData.WINDOW_STEPS) return MlRuntimeState.ML_WARMING to null
        if ((samplesSeen - FrozenVelocityModelData.WINDOW_STEPS) % FrozenVelocityModelData.UPDATE_STRIDE_STEPS != 0) {
            val previous = latestInference ?: return MlRuntimeState.ML_WARMING to null
            return stateFor(previous.oodExceedance) to previous
        }
        latestInference = model.predict(history.toTypedArray())
        inferenceUpdated = true
        return stateFor(latestInference!!.oodExceedance) to latestInference
    }

    private fun stateFor(exceedance: Double): MlRuntimeState = when {
        exceedance > HARD_OOD_EXCEEDANCE -> MlRuntimeState.ML_REJECTED
        exceedance > SOFT_OOD_EXCEEDANCE -> MlRuntimeState.ML_OOD_LIMITED
        else -> MlRuntimeState.ML_ACCEPTED
    }

    companion object {
        const val SOFT_OOD_EXCEEDANCE = 0.5
        const val HARD_OOD_EXCEEDANCE = 3.0
    }
}
