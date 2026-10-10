package org.sih26168.idrlogger.engine

import java.io.File
import kotlin.math.hypot
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.sih26168.idrlogger.model.GnssDiagnosticsSnapshot
import org.sih26168.idrlogger.model.GnssStatus
import org.sih26168.idrlogger.model.LiveIdrSample
import org.sih26168.idrlogger.model.MlOodState
import org.sih26168.idrlogger.model.Quaternion
import org.sih26168.idrlogger.model.RuntimeGnssFix
import org.sih26168.idrlogger.model.SensorAvailability
import org.sih26168.idrlogger.model.Vector3

/** Replays the preserved 2026-10-10 field export when it is present in this workspace. */
class FieldFailureReplayTest {
    @Test
    fun undergroundJourneyCannotRepeatRunawaySpeedAndVerifiedGnssReanchors() {
        val csv = File("../../results/field_failure_20261010/raw/session1/runtime_10hz.csv")
        assumeTrue("preserved field export is not installed", csv.isFile)
        val engine = IdrEngine()
        var journeyMaxSpeed = 0.0
        var stateAtJourneyEnd = NavigationState()
        var firstReturnedFixLocal: LocalPoint? = null
        var thirdReturnedFixState: NavigationState? = null
        var returnedDistinctFixes = 0
        var previousSolutionTimestamp: Long? = null

        csv.bufferedReader().use { reader ->
            val names = reader.readLine().split(',')
            val index = names.withIndex().associate { it.value to it.index }
            reader.lineSequence().forEach { line ->
                val fields = line.split(',', limit = names.size)
                val elapsed = fields.number(index, "elapsed_seconds") ?: return@forEach
                if (elapsed > 625.0) return@forEach
                val sample = fields.toSample(index)
                val state = engine.process(sample)
                if (elapsed in 95.0..614.0) {
                    journeyMaxSpeed = maxOf(journeyMaxSpeed, state.speedMps)
                    stateAtJourneyEnd = state
                }
                if (elapsed >= 614.0 && sample.gnssIsFresh && sample.gnss != null) {
                    val solutionTimestamp = sample.gnssDiagnostics.lastPhysicalGnssTimestampNs
                    if (solutionTimestamp != null && solutionTimestamp != previousSolutionTimestamp) {
                        previousSolutionTimestamp = solutionTimestamp
                        returnedDistinctFixes += 1
                        if (firstReturnedFixLocal == null && state.latitudeDeg != null) {
                            // The replay state and physical callback use the same local transform;
                            // geodetic distance is checked after the third independent callback.
                            firstReturnedFixLocal = LocalPoint(sample.gnss.longitudeDeg, sample.gnss.latitudeDeg)
                        }
                        if (returnedDistinctFixes == 3) thirdReturnedFixState = state
                    }
                }
            }
        }

        assertTrue("field replay must include the journey", stateAtJourneyEnd.sequenceId > 0)
        assertTrue(
            "stale inertial acceleration must not recreate the recorded 33.60 m/s plateau: $journeyMaxSpeed",
            journeyMaxSpeed < 25.0,
        )
        val recovered = requireNotNull(thirdReturnedFixState)
        assertEquals(LocalizationMode.GNSS_RECOVERING, recovered.localizationMode)
        assertTrue("verified large-drift recovery must perform a material correction", recovered.lastCorrectionM > 100.0)
        val fix = requireNotNull(firstReturnedFixLocal)
        val callback = recovered.run { requireNotNull(latitudeDeg) to requireNotNull(longitudeDeg) }
        val approximateDistanceM = hypot(
            (callback.second - fix.eastM) * 111_320.0 * kotlin.math.cos(Math.toRadians(callback.first)),
            (callback.first - fix.northM) * 110_540.0,
        )
        assertTrue("verified recovery must return near the consistent physical fixes: $approximateDistanceM m", approximateDistanceM < 50.0)
        println(
            "FIELD_REPLAY journey_max_speed_mps=$journeyMaxSpeed " +
                "journey_end_mode=${stateAtJourneyEnd.localizationMode} " +
                "third_fix_correction_m=${recovered.lastCorrectionM} " +
                "third_fix_distance_m=$approximateDistanceM",
        )
    }

    private fun List<String>.toSample(index: Map<String, Int>): LiveIdrSample {
        fun vector(prefix: String): Vector3? {
            val x = number(index, "${prefix}_x_${if (prefix == "magnetometer") "ut" else if (prefix == "gyroscope") "radps" else "mps2"}")
            val y = number(index, "${prefix}_y_${if (prefix == "magnetometer") "ut" else if (prefix == "gyroscope") "radps" else "mps2"}")
            val z = number(index, "${prefix}_z_${if (prefix == "magnetometer") "ut" else if (prefix == "gyroscope") "radps" else "mps2"}")
            return if (x == null || y == null || z == null) null else Vector3(x, y, z)
        }
        val qx = number(index, "rotation_qx")
        val qy = number(index, "rotation_qy")
        val qz = number(index, "rotation_qz")
        val qw = number(index, "rotation_qw")
        val rotation = if (qx == null || qy == null || qz == null || qw == null) null else Quaternion(qx, qy, qz, qw)
        val latitude = number(index, "gnss_latitude_deg")
        val longitude = number(index, "gnss_longitude_deg")
        val gnss = if (latitude == null || longitude == null) null else RuntimeGnssFix(
            latitudeDeg = latitude,
            longitudeDeg = longitude,
            altitudeM = number(index, "gnss_altitude_m"),
            speedMps = number(index, "gnss_speed_mps"),
            bearingDeg = number(index, "gnss_bearing_deg"),
            accuracyM = number(index, "gnss_accuracy_m"),
            verticalAccuracyM = number(index, "gnss_vertical_accuracy_m"),
            speedAccuracyMps = number(index, "gnss_speed_accuracy_mps"),
            bearingAccuracyDeg = number(index, "gnss_bearing_accuracy_deg"),
            provider = text(index, "gnss_provider") ?: "gps",
        )
        return LiveIdrSample(
            sequenceId = requireNotNull(number(index, "sequence_id")).toLong(),
            elapsedSeconds = requireNotNull(number(index, "elapsed_seconds")),
            monotonicTimestampNs = requireNotNull(number(index, "monotonic_timestamp_ns")).toLong(),
            wallClockUtc = text(index, "wall_clock_utc") ?: "",
            accelerometer = vector("accelerometer"),
            gyroscope = vector("gyroscope"),
            magnetometer = vector("magnetometer"),
            gravity = vector("gravity"),
            rotation = rotation,
            gnss = gnss,
            gnssFixAgeSeconds = number(index, "gnss_fix_age_seconds"),
            gnssIsFresh = boolean(index, "gnss_is_fresh"),
            gnssStatus = GnssStatus.valueOf(text(index, "gnss_status") ?: "INVALID"),
            simulatedBlackout = boolean(index, "simulated_blackout"),
            gnssDiagnostics = GnssDiagnosticsSnapshot(
                physicalCallbackCount = (number(index, "physical_gnss_callback_count") ?: 0.0).toLong(),
                latestPhysicalCallbackAgeSeconds = number(index, "latest_physical_callback_age_seconds"),
                lastPhysicalGnssTimestampNs = number(index, "last_physical_gnss_timestamp_ns")?.toLong(),
                firstValidFixTimestampNs = number(index, "first_valid_gnss_fix_timestamp_ns")?.toLong(),
                timeToFirstFixSeconds = number(index, "time_to_first_fix_seconds"),
                satellitesVisible = number(index, "satellites_visible")?.toInt(),
                satellitesUsedInFix = number(index, "satellites_used_in_fix")?.toInt(),
                gnssStatusAvailable = boolean(index, "gnss_status_available"),
                blackoutMasksRealFix = boolean(index, "blackout_masks_real_fix"),
            ),
            availability = SensorAvailability(
                accelerometer = boolean(index, "accelerometer_available"),
                gyroscope = boolean(index, "gyroscope_available"),
                magnetometer = boolean(index, "magnetometer_available"),
                gravity = boolean(index, "gravity_available"),
                rotationVector = boolean(index, "rotation_vector_available"),
                gpsProvider = boolean(index, "gps_provider_available"),
            ),
            mlOodState = text(index, "ml_ood_state")?.let(MlOodState::valueOf) ?: MlOodState.NOT_EVALUATED,
            mlFeatureExceedance = number(index, "ml_feature_exceedance"),
            mlCorrectionAccepted = text(index, "ml_correction_accepted")?.toBooleanStrictOrNull(),
        )
    }

    private fun List<String>.text(index: Map<String, Int>, name: String): String? =
        index[name]?.let(::get)?.takeIf(String::isNotBlank)

    private fun List<String>.number(index: Map<String, Int>, name: String): Double? =
        text(index, name)?.toDoubleOrNull()

    private fun List<String>.boolean(index: Map<String, Int>, name: String): Boolean =
        text(index, name)?.equals("true", ignoreCase = true) == true
}
