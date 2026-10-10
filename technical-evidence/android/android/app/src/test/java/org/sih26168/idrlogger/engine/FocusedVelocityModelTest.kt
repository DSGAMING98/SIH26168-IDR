package org.sih26168.idrlogger.engine

import kotlin.math.sin
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FocusedVelocityModelTest {
    private val model = FocusedVelocityModel()

    @Test
    fun focusedModelHasFrozenResearchContract() {
        assertEquals(14_657, model.parameterCount)
        assertEquals(50, FocusedVelocityModelData.WINDOW_STEPS)
        assertEquals(64, FocusedVelocityModelData.HIDDEN_SIZE)
        assertEquals("conditioned_forward_acceleration_mps2", model.featureOrder.first())
        assertEquals("classical_speed_mps", model.featureOrder.last())
        assertEquals("e548cac929ae78c0a6449f8bb6d0cecd772166ae0fcaf140bb1a096d4055a2c1", FocusedVelocityModelData.CHECKPOINT_SHA256)
    }

    @Test
    fun pureKotlinDirectGruMatchesPythonGoldenWindows() {
        val windows = arrayOf(
            Array(50) { DoubleArray(10) },
            Array(50) { FocusedVelocityModelData.MEANS.copyOf().also { it[it.lastIndex] = 0.0 } },
            Array(50) { row ->
                DoubleArray(10) { column ->
                    FocusedVelocityModelData.MEANS[column] +
                        0.25 * FocusedVelocityModelData.STANDARD_DEVIATIONS[column] * sin(row + column.toDouble())
                }.also { it[it.lastIndex] = 0.0 }
            },
        )
        windows.forEachIndexed { index, window ->
            val result = model.predict(window)
            assertEquals(FocusedVelocityModelData.GOLDEN_EXPECTED_SPEEDS[index], result.directSpeedMps, 1e-4)
            assertEquals(FocusedVelocityModelData.GOLDEN_EXPECTED_OOD[index], result.oodExceedance, 1e-5)
        }
    }

    @Test
    fun earlyLowDynamicsDisagreementIsSuppressed() {
        val runtime = CausalFocusedVelocity(constantPredictor(10.0))
        runtime.startBlackout(null)
        var inference: FocusedMlInference? = null
        repeat(50) { inference = runtime.update(features(classicalSpeed = 0.0)).second }
        assertTrue(runtime.inferenceUpdated)
        assertTrue(inference!!.earlySuppressed)
        assertEquals(0.0, inference!!.residualMps, 0.0)
    }

    @Test
    fun earlyGatePermanentlyOpensAfterDynamicWindow() {
        val runtime = CausalFocusedVelocity(constantPredictor(10.0))
        runtime.startBlackout(null)
        repeat(50) { runtime.update(features(forwardAcceleration = 1.0, classicalSpeed = 0.0)) }
        assertFalse(runtime.latestInference!!.earlySuppressed)
        repeat(5) { runtime.update(features(classicalSpeed = 0.0)) }
        assertFalse(runtime.latestInference!!.earlySuppressed)
        assertEquals(10.0, runtime.latestInference!!.residualMps, 0.0)
    }

    @Test
    fun reconstructedFloorAppliesOnlyAtFrozenLongOutageTransition() {
        val runtime = CausalFocusedVelocity(constantPredictor(10.0))
        runtime.startBlackout(20.0)
        repeat(449) { runtime.update(features(forwardAcceleration = 1.0, classicalSpeed = 5.0)) }
        assertFalse(runtime.latestInference!!.longFloorApplied)
        runtime.update(features(forwardAcceleration = 1.0, classicalSpeed = 5.0))
        assertTrue(runtime.latestInference!!.longFloorApplied)
        assertEquals(20.0, runtime.latestInference!!.directSpeedMps, 0.0)
        assertEquals(CausalFocusedVelocity.LONG_OUTAGE_TRANSITION_S, 45.0, 0.0)
    }

    @Test
    fun stationaryEvidencePermanentlyBlocksLongFloor() {
        val runtime = CausalFocusedVelocity(constantPredictor(10.0))
        runtime.startBlackout(20.0)
        repeat(450) { index ->
            runtime.update(features(forwardAcceleration = 1.0, stationary = index < 10, classicalSpeed = 5.0))
        }
        assertFalse(runtime.latestInference!!.longFloorApplied)
        assertEquals(10.0, runtime.latestInference!!.directSpeedMps, 0.0)
    }

    private fun constantPredictor(speedMps: Double) = DirectSpeedPredictor {
        FocusedSpeedPrediction(speedMps, 0.0)
    }

    private fun features(
        forwardAcceleration: Double = 0.0,
        stationary: Boolean = false,
        classicalSpeed: Double,
    ) = doubleArrayOf(
        forwardAcceleration,
        0.0,
        0.0,
        0.0,
        9.8066,
        40.0,
        0.5,
        0.05,
        if (stationary) 1.0 else 0.0,
        classicalSpeed,
    )
}
