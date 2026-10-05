package org.sih26168.idrlogger.engine

import kotlin.math.abs
import kotlin.math.hypot
import kotlin.math.sin
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class Phase11HardeningTest {
    @Test
    fun blackoutBeforeAlignmentHoldsPositionAndDoesNotClaimFullIdr() {
        val engine = IdrEngine()
        val initial = engine.process(
            EngineTestFixtures.sample(0, 1_000_000_000L, gnssEastM = 0.0, gnssSpeedMps = 0.0)
        )
        var state = initial
        for (index in 1..300) {
            state = engine.process(
                EngineTestFixtures.sample(
                    sequence = index.toLong(),
                    timeNs = 1_000_000_000L + index * 100_000_000L,
                    blackout = true,
                    forwardAccelerationMps2 = 0.25 + 0.03 * sin(index.toDouble()),
                    gyroZRadps = 0.015,
                    rotationYawDeg = (index % 90).toDouble(),
                )
            )
        }
        assertEquals(LocalizationMode.CALIBRATION_REQUIRED, state.localizationMode)
        assertEquals(0.0, hypot(state.eastM - initial.eastM, state.northM - initial.northM), 1e-9)
        assertEquals(0.0, state.speedMps, 1e-9)
        assertEquals(ConfidenceLevel.LOW, state.confidence)
    }

    @Test
    fun realisticStationaryNoiseIsStableForThirtySixtyAndOneHundredTwentySeconds() {
        listOf(30 to 0.08, 60 to 0.12, 120 to 0.16).forEach { (durationSeconds, bias) ->
            val result = runAlignedStationary(durationSeconds, bias)
            assertTrue("$durationSeconds s displacement=${result.finalDisplacementM}", result.finalDisplacementM < 2.0)
            assertTrue("$durationSeconds s maximum=${result.maximumDisplacementM}", result.maximumDisplacementM < 3.0)
            assertTrue(result.finalSpeedMps < 0.15)
            assertTrue(result.stationaryFraction > 0.95)
            assertTrue(result.uncertaintyEndM >= result.uncertaintyStartM)
            println(
                "PHASE11_STATIONARY duration_s=$durationSeconds final_m=${result.finalDisplacementM} " +
                    "max_m=${result.maximumDisplacementM} speed_mps=${result.finalSpeedMps} " +
                    "stationary_fraction=${result.stationaryFraction} sigma_start=${result.uncertaintyStartM} " +
                    "sigma_end=${result.uncertaintyEndM}"
            )
        }
    }

    @Test
    fun motionClassifierUsesInitializationAndHysteresis() {
        val conditioner = SensorConditioner()
        var state = MotionState.INITIALIZING
        for (index in 0 until 19) {
            state = conditioner.condition(
                EngineTestFixtures.sample(index.toLong(), 1_000_000_000L + index * 100_000_000L),
                0.1,
                0.0,
            ).motionState
        }
        assertEquals(MotionState.INITIALIZING, state)
        state = conditioner.condition(EngineTestFixtures.sample(19, 2_900_000_000L), 0.1, 0.0).motionState
        assertEquals(MotionState.LIKELY_STATIONARY, state)
        repeat(4) { index ->
            state = conditioner.condition(
                EngineTestFixtures.sample(20L + index, 3_000_000_000L + index * 100_000_000L, forwardAccelerationMps2 = 0.8),
                0.1,
                0.0,
            ).motionState
        }
        assertEquals(MotionState.LIKELY_STATIONARY, state)
        state = conditioner.condition(
            EngineTestFixtures.sample(24, 3_400_000_000L, forwardAccelerationMps2 = 0.8), 0.1, 0.0
        ).motionState
        assertEquals(MotionState.MOVING, state)
        repeat(30) { index ->
            state = conditioner.condition(
                EngineTestFixtures.sample(25L + index, 3_500_000_000L + index * 100_000_000L), 0.1, 0.0
            ).motionState
        }
        assertEquals(MotionState.LIKELY_STATIONARY, state)
    }

    @Test
    fun alignmentWorksForPortraitAndLandscapeLikeMountHeadings() {
        listOf(0.0, 90.0, -90.0, 170.0).forEach { deviceHeadingDeg ->
            val alignment = VehicleAlignment()
            repeat(6) { alignment.update(Math.toRadians(deviceHeadingDeg), 40.0, 8.0) }
            assertEquals(AlignmentState.READY, alignment.state)
            val vehicleHeading = Math.toDegrees(alignment.vehicleHeading(Math.toRadians(deviceHeadingDeg))!!)
            assertTrue(abs(wrappedDegrees(vehicleHeading - 40.0)) < 1e-6)
        }
    }

    private fun runAlignedStationary(durationSeconds: Int, bias: Double): StationaryResult {
        val engine = IdrEngine()
        var sequence = 0L
        var timeNs = 1_000_000_000L
        repeat(6) { index ->
            engine.process(
                EngineTestFixtures.sample(sequence++, timeNs, gnssEastM = index * 0.8, gnssSpeedMps = 8.0)
            )
            timeNs += 100_000_000L
        }
        repeat(50) { index ->
            engine.process(
                EngineTestFixtures.sample(
                    sequence++, timeNs, gnssEastM = 4.0, gnssSpeedMps = 0.0,
                    forwardAccelerationMps2 = bias + 0.015 * sin(index * 0.7),
                    gyroZRadps = 0.006 * sin(index * 0.3),
                    rotationYawDeg = 0.15 * sin(index * 0.2),
                    magnetometerDeltaUt = 1.5 * sin(index * 0.4),
                )
            )
            timeNs += 100_000_000L
        }
        val start = engine.snapshot().state
        var maximum = 0.0
        var stationary = 0
        var end = start
        repeat(durationSeconds * 10) { index ->
            end = engine.process(
                EngineTestFixtures.sample(
                    sequence++, timeNs, blackout = true,
                    forwardAccelerationMps2 = bias + 0.025 * sin(index * 0.71),
                    gyroZRadps = 0.009 * sin(index * 0.37),
                    rotationYawDeg = 0.20 * sin(index * 0.19),
                    magnetometerDeltaUt = 2.0 * sin(index * 0.43),
                )
            )
            timeNs += 100_000_000L
            if (end.motionState == MotionState.LIKELY_STATIONARY) stationary += 1
            maximum = maxOf(maximum, hypot(end.eastM - start.eastM, end.northM - start.northM))
        }
        return StationaryResult(
            finalDisplacementM = hypot(end.eastM - start.eastM, end.northM - start.northM),
            maximumDisplacementM = maximum,
            finalSpeedMps = end.speedMps,
            stationaryFraction = stationary.toDouble() / (durationSeconds * 10),
            uncertaintyStartM = start.horizontalUncertaintyM!!,
            uncertaintyEndM = end.horizontalUncertaintyM!!,
        )
    }

    private fun wrappedDegrees(value: Double): Double = (value + 540.0) % 360.0 - 180.0

    private data class StationaryResult(
        val finalDisplacementM: Double,
        val maximumDisplacementM: Double,
        val finalSpeedMps: Double,
        val stationaryFraction: Double,
        val uncertaintyStartM: Double,
        val uncertaintyEndM: Double,
    )
}
