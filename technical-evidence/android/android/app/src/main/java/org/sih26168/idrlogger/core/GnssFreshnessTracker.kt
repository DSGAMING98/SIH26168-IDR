package org.sih26168.idrlogger.core

import kotlin.math.max
import org.sih26168.idrlogger.model.GnssDiagnosticsSnapshot
import org.sih26168.idrlogger.model.GnssRuntimeState
import org.sih26168.idrlogger.model.GnssStatus
import org.sih26168.idrlogger.model.PhysicalGnssFix
import org.sih26168.idrlogger.model.PhysicalGnssState
import org.sih26168.idrlogger.model.RuntimeGnssFix
import org.sih26168.idrlogger.model.RuntimeGnssAvailability

class GnssFreshnessTracker(
    private val freshAgeSeconds: Double = 2.0,
) {
    private var latest: PhysicalGnssFix? = null
    private var latestFresh: PhysicalGnssFix? = null
    private var providerEnabled: Boolean = true
    private var lastInvalidTimestampNs: Long? = null
    private var recordingStartNs: Long = 0L
    private var physicalCallbackCount: Long = 0L
    private var lastPhysicalCallbackReceivedNs: Long? = null
    private var lastPhysicalTimestampNs: Long? = null
    private var firstValidFixTimestampNs: Long? = null
    private var timeToFirstFixSeconds: Double? = null
    private var satellitesVisible: Int? = null
    private var satellitesUsedInFix: Int? = null
    private var gnssStatusAvailable: Boolean = false

    init {
        require(freshAgeSeconds > 0.0)
    }

    @Synchronized
    fun setProviderEnabled(enabled: Boolean) {
        providerEnabled = enabled
    }

    @Synchronized
    fun setGnssStatusAvailable(available: Boolean) {
        gnssStatusAvailable = available
        if (!available) {
            satellitesVisible = null
            satellitesUsedInFix = null
        }
    }

    @Synchronized
    fun updateSatelliteCounts(visible: Int, usedInFix: Int) {
        require(visible >= 0 && usedInFix >= 0 && usedInFix <= visible)
        gnssStatusAvailable = true
        satellitesVisible = visible
        satellitesUsedInFix = usedInFix
    }

    @Synchronized
    fun accept(fix: PhysicalGnssFix, callbackNowNs: Long): GnssStatus {
        physicalCallbackCount += 1L
        lastPhysicalCallbackReceivedNs = callbackNowNs
        lastPhysicalTimestampNs = fix.monotonicTimestampNs
        if (!isValid(fix) || fix.monotonicTimestampNs > callbackNowNs) {
            lastInvalidTimestampNs = callbackNowNs
            return GnssStatus.INVALID
        }
        if (firstValidFixTimestampNs == null) {
            firstValidFixTimestampNs = fix.monotonicTimestampNs
            timeToFirstFixSeconds = max(0.0, (callbackNowNs - recordingStartNs) / 1_000_000_000.0)
        }
        if (latest != null && fix.monotonicTimestampNs <= latest!!.monotonicTimestampNs) {
            return GnssStatus.STALE
        }
        val callbackAge = (callbackNowNs - fix.monotonicTimestampNs) / 1_000_000_000.0
        latest = fix
        return if (callbackAge <= freshAgeSeconds) {
            // Freshness is temporal, not a movement classifier. Android is allowed to deliver a
            // newer GPS solution with the same coordinates while stationary or moving slowly.
            // Calling that callback stale made live navigation alternate between GNSS loss and
            // recovery. Replayed callbacks are still rejected above by their monotonic timestamp,
            // and IdrEngine independently consumes each physical solution timestamp only once.
            latestFresh = fix
            GnssStatus.FRESH
        } else {
            GnssStatus.STALE
        }
    }

    @Synchronized
    fun runtimeState(nowNs: Long, simulatedBlackout: Boolean): GnssRuntimeState {
        if (simulatedBlackout) {
            return GnssRuntimeState(GnssStatus.SIMULATED_BLACKOUT, ageSeconds(nowNs), false, null)
        }
        if (!providerEnabled) return GnssRuntimeState(GnssStatus.PROVIDER_DISABLED, ageSeconds(nowNs), false, null)
        val fix = latest ?: return GnssRuntimeState(
            if (lastInvalidTimestampNs != null) GnssStatus.INVALID else GnssStatus.WAITING_FOR_FIRST_FIX,
            null,
            false,
            null,
        )
        val age = max(0.0, (nowNs - fix.monotonicTimestampNs) / 1_000_000_000.0)
        val fresh = latestFresh?.monotonicTimestampNs == fix.monotonicTimestampNs && age <= freshAgeSeconds
        return GnssRuntimeState(
            if (fresh) GnssStatus.FRESH else GnssStatus.STALE,
            age,
            fresh,
            fix.toRuntime(),
        )
    }

    @Synchronized
    fun latestPhysicalFix(): PhysicalGnssFix? = latest

    @Synchronized
    fun hasValidPhysicalFix(): Boolean = firstValidFixTimestampNs != null

    @Synchronized
    fun diagnostics(nowNs: Long, simulatedBlackout: Boolean): GnssDiagnosticsSnapshot {
        val lastCallback = lastPhysicalCallbackReceivedNs
        val physicalAgeSeconds = latest?.let { max(0.0, (nowNs - it.monotonicTimestampNs) / 1_000_000_000.0) }
        val physicalState = when {
            latest == null -> PhysicalGnssState.NONE
            physicalAgeSeconds != null && physicalAgeSeconds <= freshAgeSeconds -> PhysicalGnssState.FRESH
            else -> PhysicalGnssState.STALE
        }
        val runtimeState = runtimeState(nowNs, simulatedBlackout)
        return GnssDiagnosticsSnapshot(
            physicalCallbackCount = physicalCallbackCount,
            latestPhysicalCallbackAgeSeconds = lastCallback?.let {
                max(0.0, (nowNs - it) / 1_000_000_000.0)
            },
            lastPhysicalGnssTimestampNs = lastPhysicalTimestampNs,
            firstValidFixTimestampNs = firstValidFixTimestampNs,
            timeToFirstFixSeconds = timeToFirstFixSeconds,
            satellitesVisible = satellitesVisible,
            satellitesUsedInFix = satellitesUsedInFix,
            gnssStatusAvailable = gnssStatusAvailable,
            blackoutMasksRealFix = simulatedBlackout && firstValidFixTimestampNs != null,
            physicalFixState = physicalState,
            runtimeGnssAvailability = when {
                simulatedBlackout -> RuntimeGnssAvailability.MASKED
                runtimeState.status == GnssStatus.FRESH && runtimeState.runtimeFix != null -> RuntimeGnssAvailability.AVAILABLE
                else -> RuntimeGnssAvailability.UNAVAILABLE
            },
            hasAcquiredRealFixThisSession = firstValidFixTimestampNs != null,
            blackoutMasksFreshFix = simulatedBlackout && physicalState == PhysicalGnssState.FRESH,
        )
    }

    @Synchronized
    fun reset(sessionStartNs: Long = 0L) {
        require(sessionStartNs >= 0L)
        latest = null
        latestFresh = null
        providerEnabled = true
        lastInvalidTimestampNs = null
        recordingStartNs = sessionStartNs
        physicalCallbackCount = 0L
        lastPhysicalCallbackReceivedNs = null
        lastPhysicalTimestampNs = null
        firstValidFixTimestampNs = null
        timeToFirstFixSeconds = null
        satellitesVisible = null
        satellitesUsedInFix = null
        gnssStatusAvailable = false
    }

    private fun ageSeconds(nowNs: Long): Double? = latest?.let {
        max(0.0, (nowNs - it.monotonicTimestampNs) / 1_000_000_000.0)
    }

    private fun isValid(fix: PhysicalGnssFix): Boolean =
        fix.latitudeDeg.isFinite() && fix.latitudeDeg in -90.0..90.0 &&
            fix.longitudeDeg.isFinite() && fix.longitudeDeg in -180.0..180.0 &&
            (fix.accuracyM == null || (fix.accuracyM.isFinite() && fix.accuracyM >= 0.0))

    private fun PhysicalGnssFix.toRuntime() = RuntimeGnssFix(
        latitudeDeg,
        longitudeDeg,
        altitudeM,
        speedMps,
        bearingDeg,
        accuracyM,
        verticalAccuracyM,
        speedAccuracyMps,
        bearingAccuracyDeg,
        provider,
    )

}
