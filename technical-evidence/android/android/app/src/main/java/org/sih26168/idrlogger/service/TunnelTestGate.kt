package org.sih26168.idrlogger.service

import org.sih26168.idrlogger.engine.AlignmentState
import org.sih26168.idrlogger.engine.LocalizationMode
import org.sih26168.idrlogger.engine.NavigationState

data class TunnelTestEligibility(
    val allowed: Boolean,
    val message: String,
)

/** Single safety gate for manual GNSS-loss simulation. */
object TunnelTestGate {
    fun evaluate(
        recording: Boolean,
        freshPhysicalGnssAvailable: Boolean,
        navigation: NavigationState,
    ): TunnelTestEligibility {
        val unavailable = when {
            !recording -> "Start navigation before running the tunnel test."
            navigation.localizationMode == LocalizationMode.ERROR ->
                "Localization is unavailable. Restart navigation before running the tunnel test."
            !freshPhysicalGnssAvailable ->
                "Acquire a stable GNSS fix before simulating signal loss."
            navigation.latitudeDeg == null || navigation.longitudeDeg == null ->
                "Wait for a trusted localization anchor before simulating signal loss."
            navigation.alignmentState != AlignmentState.READY ->
                "Complete phone-to-vehicle calibration before simulating signal loss."
            navigation.localizationMode != LocalizationMode.GNSS_ACTIVE ->
                "Wait until NavGhost reports GNSS ACTIVE before simulating signal loss."
            else -> null
        }
        return if (unavailable == null) {
            TunnelTestEligibility(true, "Tunnel test ready")
        } else {
            TunnelTestEligibility(false, "TUNNEL TEST UNAVAILABLE • $unavailable")
        }
    }
}
