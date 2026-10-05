package org.sih26168.idrlogger.product

import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.PI
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt
import org.sih26168.idrlogger.engine.LocalizationMode
import org.sih26168.idrlogger.engine.NavigationState
import org.sih26168.idrlogger.engine.MlRuntimeState

data class TripMetrics(
    val distanceM: Double = 0.0,
    val durationSeconds: Double = 0.0,
    val averageSpeedMps: Double = 0.0,
    val maximumSpeedMps: Double = 0.0,
    val gnssLossEvents: Int = 0,
    val gnssActiveDurationSeconds: Double = 0.0,
    val idrDurationSeconds: Double = 0.0,
    val longestIdrIntervalSeconds: Double = 0.0,
    val averageUncertaintyM: Double? = null,
    val maximumUncertaintyM: Double? = null,
    val gruAssistanceUsed: Boolean = false,
)

class TripMetricsAccumulator {
    private var firstNs = 0L
    private var previousNs = 0L
    private var previousLat: Double? = null
    private var previousLon: Double? = null
    private var previousMode: LocalizationMode? = null
    private var distanceM = 0.0
    private var speedIntegral = 0.0
    private var maxSpeed = 0.0
    private var idrSeconds = 0.0
    private var gnssSeconds = 0.0
    private var currentIdrSeconds = 0.0
    private var longestIdrSeconds = 0.0
    private var lossEvents = 0
    private var uncertaintySum = 0.0
    private var uncertaintyCount = 0L
    private var maxUncertainty: Double? = null
    private var gruUsed = false

    fun add(state: NavigationState) {
        val now = state.monotonicTimestampNs
        if (now <= 0L || (previousNs > 0L && now <= previousNs)) return
        if (firstNs == 0L) firstNs = now
        val dt = if (previousNs == 0L) 0.0 else ((now - previousNs) / 1e9).coerceIn(0.0, 2.0)
        val lat = state.latitudeDeg?.takeIf { it.isFinite() && it in -90.0..90.0 }
        val lon = state.longitudeDeg?.takeIf { it.isFinite() && it in -180.0..180.0 }
        if (lat != null && lon != null && previousLat != null && previousLon != null) {
            val step = haversineM(previousLat!!, previousLon!!, lat, lon)
            if (step <= MAX_PLAUSIBLE_STEP_M) distanceM += step
        }
        val speed = state.speedMps.takeIf { it.isFinite() }?.coerceIn(0.0, 100.0) ?: 0.0
        speedIntegral += speed * dt
        maxSpeed = maxOf(maxSpeed, speed)
        if (state.localizationMode == LocalizationMode.GNSS_ACTIVE) gnssSeconds += dt
        if (state.localizationMode in IDR_MODES) {
            idrSeconds += dt; currentIdrSeconds += dt; longestIdrSeconds = maxOf(longestIdrSeconds, currentIdrSeconds)
        } else currentIdrSeconds = 0.0
        if (state.localizationMode in IDR_MODES && previousMode !in IDR_MODES) lossEvents += 1
        state.horizontalUncertaintyM?.takeIf { it.isFinite() && it >= 0.0 }?.let {
            uncertaintySum += it; uncertaintyCount += 1
            maxUncertainty = maxOf(maxUncertainty ?: it, it)
        }
        if (state.mlState == MlRuntimeState.ML_ACCEPTED) gruUsed = true
        previousNs = now; previousLat = lat; previousLon = lon; previousMode = state.localizationMode
    }

    fun snapshot(): TripMetrics {
        val duration = if (firstNs == 0L || previousNs <= firstNs) 0.0 else (previousNs - firstNs) / 1e9
        return TripMetrics(distanceM, duration, if (duration > 0.0) speedIntegral / duration else 0.0,
            maxSpeed, lossEvents, gnssSeconds, idrSeconds, longestIdrSeconds,
            if (uncertaintyCount > 0) uncertaintySum / uncertaintyCount else null, maxUncertainty, gruUsed)
    }

    companion object {
        private const val EARTH_RADIUS_M = 6_371_008.8
        private const val MAX_PLAUSIBLE_STEP_M = 120.0
        val IDR_MODES = setOf(LocalizationMode.GNSS_DEGRADED, LocalizationMode.IDR_ACTIVE,
            LocalizationMode.GNSS_VERIFYING, LocalizationMode.GNSS_RECOVERING)

        fun haversineM(aLat: Double, aLon: Double, bLat: Double, bLon: Double): Double {
            val dLat = (bLat - aLat) * PI / 180.0
            val dLon = (bLon - aLon) * PI / 180.0
            val x = sin(dLat / 2) * sin(dLat / 2) + cos(aLat * PI / 180.0) * cos(bLat * PI / 180.0) * sin(dLon / 2) * sin(dLon / 2)
            return 2.0 * EARTH_RADIUS_M * asin(sqrt(x.coerceIn(0.0, 1.0)))
        }

        fun coordinateLabel(lat: Double?, lon: Double?): String = if (lat == null || lon == null) "Position unavailable"
            else String.format(Locale.US, "%.5f°, %.5f°", lat, lon)

        fun defaultTitle(wallTimeMs: Long): String = SimpleDateFormat("EEE, d MMM • HH:mm", Locale.getDefault()).format(Date(wallTimeMs))
    }
}
