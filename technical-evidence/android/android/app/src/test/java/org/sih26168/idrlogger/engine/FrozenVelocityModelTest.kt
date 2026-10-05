package org.sih26168.idrlogger.engine

import kotlin.math.sin
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class FrozenVelocityModelTest {
    private val model = FrozenVelocityModel()

    @Test
    fun frozenModelHasExpectedParameterAndFeatureContract() {
        assertEquals(4_257, model.parameterCount)
        assertEquals(10, model.featureOrder.size)
        assertEquals("conditioned_forward_acceleration_mps2", model.featureOrder.first())
        assertEquals("classical_speed_mps", model.featureOrder.last())
    }

    @Test
    fun pureKotlinGruMatchesThreePythonGoldenWindows() {
        val windows = arrayOf(
            Array(20) { DoubleArray(10) },
            Array(20) { FrozenVelocityModelData.MEANS.copyOf() },
            Array(20) { row ->
                DoubleArray(10) { column ->
                    FrozenVelocityModelData.MEANS[column] +
                        0.25 * FrozenVelocityModelData.STANDARD_DEVIATIONS[column] * sin(row + column.toDouble())
                }
            },
        )
        windows.forEachIndexed { index, window ->
            val result = model.predict(window)
            assertEquals(FrozenVelocityModelData.GOLDEN_EXPECTED_RESIDUALS[index], result.residualMps, 1e-4)
            assertEquals(FrozenVelocityModelData.GOLDEN_EXPECTED_OOD[index], result.oodExceedance, 1e-5)
        }
    }

    @Test
    fun hardOodWindowIsRejectedBySafetyGate() {
        val runtime = CausalMlVelocity(model)
        var state = MlRuntimeState.ML_WARMING
        repeat(20) {
            state = runtime.update(DoubleArray(10) { 1_000_000.0 }).first
        }
        assertEquals(MlRuntimeState.ML_REJECTED, state)
        assertTrue(runtime.latestInference!!.oodExceedance > CausalMlVelocity.HARD_OOD_EXCEEDANCE)
    }
}
