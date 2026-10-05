package org.sih26168.idrlogger.field

import org.sih26168.idrlogger.model.FieldTestPhase
import org.sih26168.idrlogger.model.FieldTestPreset
import org.sih26168.idrlogger.model.FieldTestStatus
import org.sih26168.idrlogger.model.MountProfile

data class FieldTestEvent(
    val type: String,
    val message: String,
    val status: FieldTestStatus,
)

data class FieldTestUpdate(
    val status: FieldTestStatus,
    val events: List<FieldTestEvent> = emptyList(),
)

/** Monotonic, driver-interaction-free field-test schedule. */
class FieldTestController {
    private var status = FieldTestStatus()
    private var phaseStartedNs = 0L

    fun snapshot(nowNs: Long? = null): FieldTestStatus = if (nowNs == null || !isTimed(status.phase)) {
        status
    } else {
        statusFor(nowNs)
    }

    fun start(
        nowNs: Long,
        testId: String,
        preset: FieldTestPreset,
        mountProfile: MountProfile,
    ): FieldTestUpdate {
        require(nowNs > 0L)
        require(testId.isNotBlank())
        phaseStartedNs = nowNs
        status = FieldTestStatus(
            testId = testId,
            preset = preset,
            mountProfile = mountProfile,
            phase = FieldTestPhase.WARMUP,
            phaseRemainingSeconds = WARMUP_SECONDS,
        )
        return FieldTestUpdate(status, listOf(event("FIELD_TEST_STARTED", "Warm-up and calibration started.")))
    }

    fun update(nowNs: Long, alignmentReady: Boolean, runtimeGnssAvailable: Boolean): FieldTestUpdate {
        if (status.phase in TERMINAL_PHASES || status.phase == FieldTestPhase.IDLE) return FieldTestUpdate(status)
        val ready = alignmentReady && runtimeGnssAvailable
        val elapsed = elapsedSeconds(nowNs)
        val next = when (status.phase) {
            FieldTestPhase.WARMUP -> if (elapsed >= WARMUP_SECONDS) {
                if (ready) FieldTestPhase.BASELINE else FieldTestPhase.WAITING_FOR_READY
            } else null
            FieldTestPhase.WAITING_FOR_READY -> if (ready) FieldTestPhase.BASELINE else null
            FieldTestPhase.BASELINE -> if (elapsed >= BASELINE_SECONDS) FieldTestPhase.BLACKOUT else null
            FieldTestPhase.BLACKOUT -> if (elapsed >= requireNotNull(status.preset).blackoutDurationSeconds) FieldTestPhase.RECOVERY else null
            FieldTestPhase.RECOVERY -> if (elapsed >= RECOVERY_SECONDS) FieldTestPhase.COMPLETE else null
            else -> null
        }
        if (next == null) {
            status = statusFor(nowNs)
            return FieldTestUpdate(status)
        }
        val previous = status.phase
        phaseStartedNs = nowNs
        status = status.copy(phase = next, phaseElapsedSeconds = 0.0, blackoutActive = next == FieldTestPhase.BLACKOUT)
        status = statusFor(nowNs)
        val events = mutableListOf<FieldTestEvent>()
        when (next) {
            FieldTestPhase.WAITING_FOR_READY -> events += event(
                "FIELD_TEST_WAITING_FOR_READY",
                "Warm-up complete; waiting automatically for GNSS ACTIVE and alignment READY.",
            )
            FieldTestPhase.BASELINE -> events += event("FIELD_TEST_BASELINE_STARTED", "Trusted-GNSS baseline started.")
            FieldTestPhase.BLACKOUT -> events += event(
                "FIELD_TEST_BLACKOUT_STARTED",
                "Automatic ${status.preset!!.blackoutDurationSeconds}-second runtime GNSS blackout started.",
            )
            FieldTestPhase.RECOVERY -> {
                events += event("FIELD_TEST_BLACKOUT_ENDED", "Automatic runtime GNSS blackout ended.")
                events += event("FIELD_TEST_RECOVERY_STARTED", "GNSS verification and bounded recovery window started.")
            }
            FieldTestPhase.COMPLETE -> {
                events += event("FIELD_TEST_RECOVERY_COMPLETED", "Automatic recovery observation completed.")
                events += event(
                    "FIELD_TEST_COMPLETED",
                    "Automatic protocol complete; stop safely while parked and export the session.",
                )
            }
            else -> Unit
        }
        check(!(previous == FieldTestPhase.BLACKOUT && status.blackoutActive))
        return FieldTestUpdate(status, events)
    }

    fun cancel(nowNs: Long): FieldTestUpdate {
        if (status.phase in TERMINAL_PHASES || status.phase == FieldTestPhase.IDLE) return FieldTestUpdate(status)
        status = statusFor(nowNs).copy(phase = FieldTestPhase.CANCELLED, phaseRemainingSeconds = null, blackoutActive = false)
        return FieldTestUpdate(status, listOf(event("FIELD_TEST_CANCELLED", "Automatic field test cancelled.")))
    }

    fun reset() {
        status = FieldTestStatus()
        phaseStartedNs = 0L
    }

    private fun statusFor(nowNs: Long): FieldTestStatus {
        val elapsed = elapsedSeconds(nowNs)
        val duration = durationFor(status.phase)
        return status.copy(
            phaseElapsedSeconds = elapsed,
            phaseRemainingSeconds = duration?.let { (it - elapsed).coerceAtLeast(0.0) },
            blackoutActive = status.phase == FieldTestPhase.BLACKOUT,
        )
    }

    private fun elapsedSeconds(nowNs: Long): Double = ((nowNs - phaseStartedNs).coerceAtLeast(0L)) / 1e9

    private fun durationFor(phase: FieldTestPhase): Double? = when (phase) {
        FieldTestPhase.WARMUP -> WARMUP_SECONDS
        FieldTestPhase.BASELINE -> BASELINE_SECONDS
        FieldTestPhase.BLACKOUT -> status.preset?.blackoutDurationSeconds?.toDouble()
        FieldTestPhase.RECOVERY -> RECOVERY_SECONDS
        else -> null
    }

    private fun event(type: String, message: String) = FieldTestEvent(type, message, status)

    private fun isTimed(phase: FieldTestPhase) = durationFor(phase) != null

    companion object {
        const val WARMUP_SECONDS = 30.0
        const val BASELINE_SECONDS = 20.0
        const val RECOVERY_SECONDS = 30.0
        private val TERMINAL_PHASES = setOf(FieldTestPhase.COMPLETE, FieldTestPhase.CANCELLED)
    }
}
