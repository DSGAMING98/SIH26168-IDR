package org.sih26168.idrlogger.core

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.location.GnssStatus
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import java.time.Instant
import org.sih26168.idrlogger.model.PhysicalGnssFix

class GnssLocationRepository(
    private val context: Context,
    private val tracker: GnssFreshnessTracker,
    private val isSimulatedBlackout: () -> Boolean,
    private val onPhysicalFix: (PhysicalGnssFix, org.sih26168.idrlogger.model.GnssStatus, Boolean) -> Unit,
    private val onEvent: (String, String) -> Unit,
) : LocationListener {
    private val locationManager = context.getSystemService(LocationManager::class.java)
    private var thread: HandlerThread? = null
    private var gnssCallback: GnssStatus.Callback? = null
    private var running = false

    val gpsProviderAvailable: Boolean
        get() = locationManager.allProviders.contains(LocationManager.GPS_PROVIDER)

    @SuppressLint("MissingPermission")
    fun start(): Boolean {
        if (running) return true
        if (context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            onEvent("PERMISSION_DENIED", "ACCESS_FINE_LOCATION is required for GPS_PROVIDER")
            return false
        }
        if (!gpsProviderAvailable) {
            tracker.setProviderEnabled(false)
            onEvent("GNSS_UNAVAILABLE", "GPS_PROVIDER is absent")
            return false
        }
        thread = HandlerThread("IdrGpsProvider").also { it.start() }
        val handler = Handler(thread!!.looper)
        return try {
            locationManager.requestLocationUpdates(LocationManager.GPS_PROVIDER, 0L, 0f, this, thread!!.looper)
            gnssCallback = object : GnssStatus.Callback() {
                override fun onStarted() = onEvent("GNSS_STARTED", "Satellite search started")
                override fun onStopped() = onEvent("GNSS_STOPPED", "Satellite reporting stopped")
                override fun onFirstFix(ttffMillis: Int) = onEvent("GNSS_FIRST_FIX", "TTFF ${ttffMillis} ms")
                override fun onSatelliteStatusChanged(status: GnssStatus) {
                    var used = 0
                    for (index in 0 until status.satelliteCount) if (status.usedInFix(index)) used += 1
                    tracker.updateSatelliteCounts(status.satelliteCount, used)
                    onEvent("GNSS_SATELLITES", "visible=${status.satelliteCount},used=$used")
                }
            }
            val statusRegistered = locationManager.registerGnssStatusCallback(gnssCallback!!, handler)
            tracker.setGnssStatusAvailable(statusRegistered)
            onEvent(
                if (statusRegistered) "GNSS_STATUS_AVAILABLE" else "GNSS_STATUS_UNAVAILABLE",
                if (statusRegistered) "GnssStatus.Callback registered" else "Satellite counts unavailable",
            )
            if (!statusRegistered) gnssCallback = null
            tracker.setProviderEnabled(locationManager.isProviderEnabled(LocationManager.GPS_PROVIDER))
            running = true
            true
        } catch (error: Exception) {
            onEvent("GNSS_ERROR", error.message ?: error.javaClass.simpleName)
            runCatching { locationManager.removeUpdates(this) }
            gnssCallback?.let { callback -> runCatching { locationManager.unregisterGnssStatusCallback(callback) } }
            gnssCallback = null
            thread?.quitSafely()
            thread = null
            running = false
            false
        }
    }

    fun stop() {
        if (!running) return
        locationManager.removeUpdates(this)
        gnssCallback?.let(locationManager::unregisterGnssStatusCallback)
        gnssCallback = null
        thread?.quitSafely()
        thread = null
        running = false
    }

    override fun onLocationChanged(location: Location) {
        if (!running || location.provider != LocationManager.GPS_PROVIDER) return
        val fix = PhysicalGnssFix(
            monotonicTimestampNs = location.elapsedRealtimeNanos,
            wallClockUtc = Instant.ofEpochMilli(location.time).toString(),
            latitudeDeg = location.latitude,
            longitudeDeg = location.longitude,
            altitudeM = if (location.hasAltitude()) location.altitude else null,
            speedMps = if (location.hasSpeed()) location.speed.toDouble() else null,
            bearingDeg = if (location.hasBearing()) location.bearing.toDouble() else null,
            accuracyM = if (location.hasAccuracy()) location.accuracy.toDouble() else null,
            verticalAccuracyM = if (Build.VERSION.SDK_INT >= 26 && location.hasVerticalAccuracy()) location.verticalAccuracyMeters.toDouble() else null,
            speedAccuracyMps = if (Build.VERSION.SDK_INT >= 26 && location.hasSpeedAccuracy()) location.speedAccuracyMetersPerSecond.toDouble() else null,
            bearingAccuracyDeg = if (Build.VERSION.SDK_INT >= 26 && location.hasBearingAccuracy()) location.bearingAccuracyDegrees.toDouble() else null,
            provider = LocationManager.GPS_PROVIDER,
        )
        val callbackNow = SystemClock.elapsedRealtimeNanos()
        val hadValidFix = tracker.hasValidPhysicalFix()
        val status = tracker.accept(fix, callbackNow)
        if (!hadValidFix && tracker.hasValidPhysicalFix()) {
            val timing = tracker.diagnostics(callbackNow, isSimulatedBlackout()).timeToFirstFixSeconds
            onEvent("GNSS_VALID_FIRST_FIX", "time_to_first_fix_seconds=${timing ?: "unavailable"}")
        }
        onPhysicalFix(fix, status, isSimulatedBlackout() && tracker.hasValidPhysicalFix())
    }

    override fun onProviderEnabled(provider: String) {
        if (provider == LocationManager.GPS_PROVIDER) {
            tracker.setProviderEnabled(true)
            onEvent("GNSS_PROVIDER_ENABLED", provider)
        }
    }

    override fun onProviderDisabled(provider: String) {
        if (provider == LocationManager.GPS_PROVIDER) {
            tracker.setProviderEnabled(false)
            onEvent("GNSS_PROVIDER_DISABLED", provider)
        }
    }

    @Deprecated("Legacy callback retained for minSdk compatibility")
    override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) = Unit
}
