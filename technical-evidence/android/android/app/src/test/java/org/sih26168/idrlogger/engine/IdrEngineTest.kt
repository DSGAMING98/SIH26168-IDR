package org.sih26168.idrlogger.engine

import kotlin.math.hypot
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.sih26168.idrlogger.model.GnssStatus

class IdrEngineTest {
    @Test
    fun invalidOrLowQualityGnssSpeedCannotPoisonInitialization() {
        val invalidEngine = IdrEngine()
        val invalidSample = EngineTestFixtures.sample(0, 1_000_000_000L, gnssEastM = 0.0).let {
            it.copy(gnss = it.gnss!!.copy(speedMps = Double.NaN))
        }
        val invalidState = invalidEngine.process(invalidSample)
        assertTrue(invalidState.speedMps.isFinite())
        assertTrue(invalidState.speedMps < 0.1)

        val inaccurateEngine = IdrEngine()
        val inaccurateSample = EngineTestFixtures.sample(0, 1_000_000_000L, gnssEastM = 0.0, gnssSpeedMps = 30.0).let {
            it.copy(gnss = it.gnss!!.copy(speedAccuracyMps = 12.0))
        }
        val inaccurateState = inaccurateEngine.process(inaccurateSample)
        assertTrue(inaccurateState.speedMps < 0.1)
    }

    @Test
    fun trustedMovingGnssVetoesContradictoryInertialStop() {
        val engine = IdrEngine()
        var sequence = 0L
        var timeNs = 1_000_000_000L
        repeat(10) {
            engine.process(EngineTestFixtures.sample(sequence++, timeNs, gnssEastM = sequence * 0.8, forwardAccelerationMps2 = -0.8))
            timeNs += 100_000_000L
        }
        var state = NavigationState()
        repeat(40) {
            state = engine.process(EngineTestFixtures.sample(sequence++, timeNs, gnssEastM = sequence * 0.8, gnssSpeedMps = 8.0))
            timeNs += 100_000_000L
        }
        assertTrue("trusted 8 m/s GNSS must prevent a false stop: ${state.speedMps}", state.speedMps > 3.0)
        assertTrue(state.eastM > 15.0)
    }

    @Test
    fun poorAccuracyFixCannotBecomeNavigationAnchor() {
        val engine = IdrEngine()
        val state = engine.process(
            EngineTestFixtures.sample(
                sequence = 0,
                timeNs = 1_000_000_000L,
                gnssEastM = 250.0,
                gnssSpeedMps = 0.0,
                gnssAccuracyM = 80.0,
            )
        )
        assertEquals(LocalizationMode.WAITING_FOR_GNSS, state.localizationMode)
        assertEquals(null, state.latitudeDeg)
        assertTrue(engine.snapshot().trajectory.isEmpty())
    }

    @Test
    fun tenMinuteStationaryIndoorGnssScatterDoesNotBecomeATrajectory() {
        val engine = IdrEngine()
        var state = NavigationState()
        val samples = 6_000
        for (index in 0 until samples) {
            // Deterministic multi-frequency scatter spans roughly 40 m despite reported 5.7 m
            // accuracy, matching the failure mode seen on the physical phone indoors.
            val east = 18.0 * kotlin.math.sin(index * 0.071) + 4.0 * kotlin.math.sin(index * 0.013)
            val north = 16.0 * kotlin.math.cos(index * 0.053) - 3.0 * kotlin.math.sin(index * 0.019)
            state = engine.process(
                EngineTestFixtures.sample(
                    sequence = index.toLong(),
                    timeNs = 1_000_000_000L + index * 100_000_000L,
                    gnssEastM = if (index == 0) 0.0 else east,
                    gnssNorthM = if (index == 0) 0.0 else north,
                    gnssSpeedMps = 0.0,
                    gnssBearingDeg = (index * 37.0) % 360.0,
                    gnssAccuracyM = 5.7,
                    forwardAccelerationMps2 = if (index % 2 == 0) 0.006 else -0.006,
                    gyroZRadps = if (index % 3 == 0) 0.001 else -0.001,
                )
            )
        }
        assertEquals(LocalizationMode.CALIBRATING, state.localizationMode)
        assertEquals(MotionState.LIKELY_STATIONARY, state.motionState)
        assertTrue(state.speedMps < 0.05)
        assertTrue(hypot(state.eastM, state.northM) < 0.25)
        assertTrue("pre-alignment stationary scatter must not create history", engine.snapshot().trajectory.isEmpty())
    }

    @Test
    fun slowWalkWithZeroReportedGnssSpeedStillTracksPosition() {
        val engine = IdrEngine()
        var state = NavigationState()
        for (index in 0..80) {
            state = engine.process(
                EngineTestFixtures.sample(
                    sequence = index.toLong(),
                    timeNs = 1_000_000_000L + index * 100_000_000L,
                    gnssEastM = index * 0.12,
                    gnssSpeedMps = 0.0,
                    forwardAccelerationMps2 = if (index % 2 == 0) 0.9 else -0.9,
                )
            )
        }
        assertEquals(AlignmentState.CALIBRATING, state.alignmentState)
        assertEquals(LocalizationMode.CALIBRATING, state.localizationMode)
        assertTrue("slow walk must not remain at its first GNSS anchor: east=${state.eastM}", state.eastM > 5.0)
    }

    @Test
    fun gnssInitializesAndMovingBlackoutContinuesWithoutMarkerFreeze() {
        val engine = IdrEngine()
        val active = EngineTestFixtures.calibrateMoving(engine)
        assertEquals(AlignmentState.READY, active.alignmentState)
        assertEquals(LocalizationMode.GNSS_ACTIVE, active.localizationMode)
        val startEast = active.eastM
        var state = active
        for (index in 6 until 36) {
            state = engine.process(
                EngineTestFixtures.sample(
                    sequence = index.toLong(),
                    timeNs = 1_000_000_000L + index * 100_000_000L,
                    blackout = true,
                )
            )
        }
        assertEquals(LocalizationMode.IDR_ACTIVE, state.localizationMode)
        assertTrue("IDR marker must continue", state.eastM - startEast > 10.0)
        assertTrue(state.drDurationSeconds >= 2.9)
        assertTrue(state.horizontalUncertaintyM!! >= active.horizontalUncertaintyM!!)
        println(
            "PHASE10_BLACKOUT propagation_m=${state.eastM - startEast} " +
                "dr_s=${state.drDurationSeconds} sigma_start=${active.horizontalUncertaintyM} sigma_end=${state.horizontalUncertaintyM}"
        )
    }

    @Test(expected = IllegalArgumentException::class)
    fun blackoutBoundaryRejectsAnyRuntimeGnssLeakage() {
        val engine = IdrEngine()
        EngineTestFixtures.calibrateMoving(engine)
        val leaked = EngineTestFixtures.sample(6, 1_600_000_000L, gnssEastM = 4.8).copy(
            simulatedBlackout = true,
            gnssStatus = GnssStatus.SIMULATED_BLACKOUT,
        )
        engine.process(leaked)
    }

    @Test
    fun stationaryNoiseActivatesZuptAndDoesNotExplode() {
        val engine = IdrEngine()
        engine.process(
            EngineTestFixtures.sample(
                sequence = 0,
                timeNs = 1_000_000_000L,
                gnssEastM = 0.0,
                gnssSpeedMps = 0.0,
                gnssBearingDeg = 0.0,
            )
        )
        var state = NavigationState()
        for (index in 1 until 101) {
            state = engine.process(
                EngineTestFixtures.sample(
                    sequence = index.toLong(),
                    timeNs = 1_000_000_000L + index * 100_000_000L,
                    blackout = true,
                    forwardAccelerationMps2 = if (index % 2 == 0) 0.01 else -0.01,
                    gyroZRadps = if (index % 2 == 0) 0.002 else -0.002,
                )
            )
        }
        assertEquals(MotionState.LIKELY_STATIONARY, state.motionState)
        assertTrue(state.speedMps < 0.05)
        val displacement = hypot(state.eastM, state.northM)
        assertTrue(displacement < 1.0)
        println("PHASE10_STATIONARY speed_mps=${state.speedMps} displacement_m=$displacement")
    }

    @Test
    fun reacquisitionVerifiesThenRecoversWithBoundedCorrection() {
        val engine = IdrEngine()
        EngineTestFixtures.calibrateMoving(engine)
        var state = NavigationState()
        for (index in 6 until 36) {
            state = engine.process(
                EngineTestFixtures.sample(
                    sequence = index.toLong(),
                    timeNs = 1_000_000_000L + index * 100_000_000L,
                    blackout = true,
                    forwardAccelerationMps2 = 0.8,
                )
            )
        }
        val beforeRecoveryEast = state.eastM
        state = engine.process(EngineTestFixtures.sample(36, 4_600_000_000L, gnssEastM = 24.0, gnssSpeedMps = 0.0))
        assertEquals(LocalizationMode.GNSS_VERIFYING, state.localizationMode)
        state = engine.process(EngineTestFixtures.sample(37, 4_700_000_000L, gnssEastM = 24.0, gnssSpeedMps = 0.0))
        assertEquals(LocalizationMode.GNSS_VERIFYING, state.localizationMode)
        state = engine.process(EngineTestFixtures.sample(38, 4_800_000_000L, gnssEastM = 24.0, gnssSpeedMps = 0.0))
        assertEquals(LocalizationMode.GNSS_RECOVERING, state.localizationMode)
        val initialInnovation = state.gnssInnovationM!!
        assertTrue(initialInnovation.isFinite())
        assertTrue(state.lastCorrectionM <= 0.5 + 1e-9)
        var maximumCorrection = state.lastCorrectionM
        for (index in 39 until 111) {
            state = engine.process(
                EngineTestFixtures.sample(
                    sequence = index.toLong(),
                    timeNs = 1_000_000_000L + index * 100_000_000L,
                    gnssEastM = 24.0,
                    gnssSpeedMps = 0.0,
                )
            )
            maximumCorrection = maxOf(maximumCorrection, state.lastCorrectionM)
            assertTrue(state.lastCorrectionM <= 0.5 + 1e-9)
        }
        assertNotEquals(LocalizationMode.GNSS_VERIFYING, state.localizationMode)
        val finalError = kotlin.math.abs(state.eastM - 24.0)
        assertTrue("before=$beforeRecoveryEast final=${state.eastM} error=$finalError", finalError < kotlin.math.abs(beforeRecoveryEast - 24.0))
        println(
            "PHASE10_RECOVERY innovation_m=$initialInnovation max_correction_m=$maximumCorrection " +
                "final_error_m=$finalError final_mode=${state.localizationMode}"
        )
    }

    @Test
    fun repeatedSnapshotOfOnePhysicalCallbackCannotCompleteVerification() {
        val engine = IdrEngine()
        EngineTestFixtures.calibrateMoving(engine)
        for (index in 6 until 36) {
            engine.process(
                EngineTestFixtures.sample(
                    sequence = index.toLong(),
                    timeNs = 1_000_000_000L + index * 100_000_000L,
                    blackout = true,
                )
            )
        }
        val callbackTimestamp = 4_600_000_000L
        var state = engine.process(
            EngineTestFixtures.sample(
                sequence = 36,
                timeNs = callbackTimestamp,
                gnssEastM = 24.0,
                gnssSolutionTimestampNs = callbackTimestamp,
            )
        )
        assertEquals(LocalizationMode.GNSS_VERIFYING, state.localizationMode)
        state = engine.process(
            EngineTestFixtures.sample(
                sequence = 37,
                timeNs = 4_700_000_000L,
                gnssEastM = 24.0,
                locationAgeS = 0.1,
                gnssSolutionTimestampNs = callbackTimestamp,
            )
        )
        assertEquals(LocalizationMode.GNSS_VERIFYING, state.localizationMode)
        state = engine.process(
            EngineTestFixtures.sample(
                sequence = 38,
                timeNs = 4_800_000_000L,
                gnssEastM = 24.8,
                gnssSolutionTimestampNs = 4_800_000_000L,
            )
        )
        assertEquals(LocalizationMode.GNSS_VERIFYING, state.localizationMode)
        state = engine.process(
            EngineTestFixtures.sample(
                sequence = 39,
                timeNs = 4_900_000_000L,
                gnssEastM = 25.1,
                gnssSolutionTimestampNs = 4_900_000_000L,
            )
        )
        assertEquals(LocalizationMode.GNSS_RECOVERING, state.localizationMode)
    }

    @Test
    fun inconsistentReturnedFixCannotBorrowVerificationTrust() {
        val engine = IdrEngine()
        EngineTestFixtures.calibrateMoving(engine)
        for (index in 6 until 80) {
            engine.process(EngineTestFixtures.sample(index.toLong(), 1_000_000_000L + index * 100_000_000L, blackout = true))
        }
        var state = engine.process(EngineTestFixtures.sample(80, 9_000_000_000L, gnssEastM = 40.0))
        assertEquals(LocalizationMode.GNSS_VERIFYING, state.localizationMode)
        state = engine.process(EngineTestFixtures.sample(81, 9_100_000_000L, gnssEastM = 41.0))
        assertEquals(LocalizationMode.GNSS_VERIFYING, state.localizationMode)
        state = engine.process(EngineTestFixtures.sample(82, 9_200_000_000L, gnssEastM = 900.0))
        assertEquals(LocalizationMode.GNSS_VERIFYING, state.localizationMode)
        state = engine.process(EngineTestFixtures.sample(83, 9_300_000_000L, gnssEastM = 901.0))
        assertEquals(LocalizationMode.GNSS_VERIFYING, state.localizationMode)
        state = engine.process(EngineTestFixtures.sample(84, 9_400_000_000L, gnssEastM = 902.0))
        assertEquals(LocalizationMode.GNSS_RECOVERING, state.localizationMode)
    }

    @Test
    fun longHighUncertaintyDenialReanchorsOnlyAfterThreeConsistentFixes() {
        val engine = IdrEngine()
        EngineTestFixtures.calibrateMoving(engine)
        var state = NavigationState()
        for (index in 6 until 1_206) {
            state = engine.process(
                EngineTestFixtures.sample(
                    index.toLong(),
                    1_000_000_000L + index * 100_000_000L,
                    blackout = true,
                    forwardAccelerationMps2 = 1.2,
                )
            )
        }
        assertTrue(state.horizontalUncertaintyM!! > 50.0)
        val before = state.eastM
        state = engine.process(EngineTestFixtures.sample(1_206, 121_600_000_000L, gnssEastM = 100.0, gnssSpeedMps = 0.0))
        assertEquals(LocalizationMode.GNSS_VERIFYING, state.localizationMode)
        state = engine.process(EngineTestFixtures.sample(1_207, 121_700_000_000L, gnssEastM = 101.0, gnssSpeedMps = 0.0))
        assertEquals(LocalizationMode.GNSS_VERIFYING, state.localizationMode)
        state = engine.process(EngineTestFixtures.sample(1_208, 121_800_000_000L, gnssEastM = 100.5, gnssSpeedMps = 0.0))
        assertEquals(LocalizationMode.GNSS_RECOVERING, state.localizationMode)
        assertTrue("large drift must be replaced by verified physical fixes: before=$before after=${state.eastM}", kotlin.math.abs(state.eastM - 100.5) < 15.0)
        assertTrue(state.lastCorrectionM > 100.0)
    }

    @Test
    fun runtimePositionDependsOnInertialMotionNotAPlannedRoute() {
        val coasting = IdrEngine()
        val accelerating = IdrEngine()
        EngineTestFixtures.calibrateMoving(coasting)
        EngineTestFixtures.calibrateMoving(accelerating)
        var first = NavigationState()
        var second = NavigationState()
        for (index in 6 until 30) {
            val timestamp = 1_000_000_000L + index * 100_000_000L
            first = coasting.process(EngineTestFixtures.sample(index.toLong(), timestamp, blackout = true))
            second = accelerating.process(
                EngineTestFixtures.sample(index.toLong(), timestamp, blackout = true, forwardAccelerationMps2 = 1.0)
            )
        }
        assertTrue(second.eastM > first.eastM)
    }

    @Test
    fun longGnssDenialCannotReportRunawayMetroSpeed() {
        val engine = IdrEngine()
        EngineTestFixtures.calibrateMoving(engine)
        var state = NavigationState()
        for (index in 6 until 1_206) {
            state = engine.process(
                EngineTestFixtures.sample(
                    sequence = index.toLong(),
                    timeNs = 1_000_000_000L + index * 100_000_000L,
                    blackout = true,
                    forwardAccelerationMps2 = 1.2,
                )
            )
        }
        assertEquals(LocalizationMode.IDR_ACTIVE, state.localizationMode)
        assertTrue("uncorrected speed must remain inside the safety envelope: ${state.speedMps}", state.speedMps <= 15.0 + 1e-9)
    }

    @Test
    fun metroBrakingThenStationaryEvidenceArrestsADriftedSpeed() {
        val engine = IdrEngine()
        EngineTestFixtures.calibrateMoving(engine)
        var sequence = 6L
        var timeNs = 1_600_000_000L
        var state = NavigationState()
        repeat(120) {
            state = engine.process(EngineTestFixtures.sample(sequence++, timeNs, blackout = true, forwardAccelerationMps2 = 1.2))
            timeNs += 100_000_000L
        }
        assertTrue(state.speedMps > 8.0)
        repeat(18) {
            state = engine.process(EngineTestFixtures.sample(sequence++, timeNs, blackout = true, forwardAccelerationMps2 = -1.2))
            timeNs += 100_000_000L
        }
        repeat(80) {
            state = engine.process(EngineTestFixtures.sample(sequence++, timeNs, blackout = true, forwardAccelerationMps2 = 0.0))
            timeNs += 100_000_000L
        }
        assertEquals(MotionState.LIKELY_STATIONARY, state.motionState)
        assertTrue("confirmed station stop must arrest drifted velocity: ${state.speedMps}", state.speedMps < 0.1)
    }

    @Test
    fun metroDepartureAfterConfirmedStopContinuesThroughSmoothCruise() {
        val engine = IdrEngine()
        EngineTestFixtures.calibrateMoving(engine)
        var sequence = 6L
        var timeNs = 1_600_000_000L
        var state = NavigationState()

        repeat(18) {
            state = engine.process(EngineTestFixtures.sample(sequence++, timeNs, blackout = true, forwardAccelerationMps2 = -1.2, magnetometerDeltaUt = 100.0))
            timeNs += 100_000_000L
        }
        repeat(50) {
            state = engine.process(EngineTestFixtures.sample(sequence++, timeNs, blackout = true, forwardAccelerationMps2 = 0.0, magnetometerDeltaUt = 100.0))
            timeNs += 100_000_000L
        }
        assertTrue("first station stop must be held", state.speedMps < 0.1)

        repeat(30) {
            state = engine.process(EngineTestFixtures.sample(sequence++, timeNs, blackout = true, forwardAccelerationMps2 = 0.7, magnetometerDeltaUt = 100.0))
            timeNs += 100_000_000L
        }
        val departureEastM = state.eastM
        assertTrue("departure must release the stop latch: ${state.speedMps}", state.speedMps > 0.1)

        repeat(250) {
            state = engine.process(EngineTestFixtures.sample(sequence++, timeNs, blackout = true, forwardAccelerationMps2 = 0.0, magnetometerDeltaUt = 100.0))
            timeNs += 100_000_000L
        }
        assertTrue("smooth tunnel cruise must not freeze again: ${state.speedMps}", state.speedMps > 0.1)
        assertTrue("position must continue after departure", state.eastM > departureEastM + 3.0)
    }

    @Test
    fun tunnelMagneticHeadingChangesCannotBendTheDeadReckonedRoute() {
        val engine = IdrEngine()
        EngineTestFixtures.calibrateMoving(engine)
        var state = NavigationState()
        repeat(120) { index ->
            state = engine.process(
                EngineTestFixtures.sample(
                    sequence = 6L + index,
                    timeNs = 1_600_000_000L + index * 100_000_000L,
                    blackout = true,
                    rotationYawDeg = if (index % 2 == 0) 135.0 else -120.0,
                )
            )
        }
        assertEquals(LocalizationMode.IDR_ACTIVE, state.localizationMode)
        assertTrue("gyro-straight tunnel travel must remain eastbound: ${state.headingDeg}", state.headingDeg in 80.0..100.0)
        assertTrue("magnetic heading changes must not create a loop: north=${state.northM}", kotlin.math.abs(state.northM) < 5.0)
        assertTrue("tunnel estimate should continue forward: east=${state.eastM}", state.eastM > 50.0)
    }

    @Test
    fun nonMonotonicAndOversizedTimeStepsAreDroppedAndRebaselined() {
        val engine = IdrEngine()
        val anchored = engine.process(EngineTestFixtures.sample(0, 1_000_000_000L, gnssEastM = 0.0))
        val duplicate = engine.process(EngineTestFixtures.sample(1, 1_000_000_000L, blackout = true))
        assertEquals(anchored.eastM, duplicate.eastM, 0.0)
        assertTrue(duplicate.message.contains("sample dropped"))
        val oversized = engine.process(EngineTestFixtures.sample(2, 2_000_000_000L, blackout = true))
        assertEquals(anchored.eastM, oversized.eastM, 0.0)
        assertTrue(oversized.message.contains("sample dropped"))
    }
}
