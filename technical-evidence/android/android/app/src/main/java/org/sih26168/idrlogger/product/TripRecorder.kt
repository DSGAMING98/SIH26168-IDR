package org.sih26168.idrlogger.product

import java.util.concurrent.Executor
import java.util.concurrent.Executors
import org.sih26168.idrlogger.engine.NavigationState
import android.os.Build
import org.sih26168.idrlogger.BuildConfig

interface TripStore {
    fun create(trip: TripEntity): Long
    fun addSample(sample: TripSampleEntity)
    fun update(trip: TripEntity)
    fun markAbandonedInterrupted()
}

class RoomTripStore(private val dao: TripDao) : TripStore {
    override fun create(trip: TripEntity) = dao.insertTrip(trip)
    override fun addSample(sample: TripSampleEntity) { dao.insertSample(sample) }
    override fun update(trip: TripEntity) { dao.updateTrip(trip) }
    override fun markAbandonedInterrupted() { dao.markAbandonedTripsInterrupted() }
}

/** One recorder per service. Calls are cheap; all Room I/O is serialized off the 10 Hz runtime thread. */
class TripRecorder(
    private val store: TripStore,
    private val executor: Executor = Executors.newSingleThreadExecutor(),
) {
    private data class Active(val token: Long, val trip: TripEntity, val metrics: TripMetricsAccumulator = TripMetricsAccumulator(), var lastSavedNs: Long = 0L)
    @Volatile private var active: Active? = null
    private var nextToken = 1L

    fun recoverInterruptedTrips() = executor.execute { store.markAbandonedInterrupted() }

    @Synchronized fun start(wallTimeMs: Long, sessionDirectory: String?, renderer: String = "AUTO"): Long {
        val token = nextToken++
        val trip = TripEntity().apply {
            startWallTimeMs = wallTimeMs; title = TripMetricsAccumulator.defaultTitle(wallTimeMs)
            status = "RUNNING"; this.sessionDirectory = sessionDirectory
            rendererUsed = renderer; appVersion = BuildConfig.VERSION_NAME; deviceModel = "${Build.MANUFACTURER} ${Build.MODEL}".trim()
        }
        val state = Active(token, trip)
        active = state
        executor.execute { trip.id = store.create(trip) }
        return token
    }

    @Synchronized fun record(state: NavigationState, wallTimeMs: Long) {
        val current = active ?: return
        current.metrics.add(state)
        val lat = state.latitudeDeg ?: return
        val lon = state.longitudeDeg ?: return
        if (!lat.isFinite() || !lon.isFinite() || state.monotonicTimestampNs - current.lastSavedNs < SAMPLE_PERIOD_NS) return
        current.lastSavedNs = state.monotonicTimestampNs
        if (current.trip.startLatitudeDeg == null) { current.trip.startLatitudeDeg = lat; current.trip.startLongitudeDeg = lon }
        current.trip.endLatitudeDeg = lat; current.trip.endLongitudeDeg = lon
        val sample = TripSampleEntity().apply {
            this.wallTimeMs = wallTimeMs; elapsedSeconds = current.metrics.snapshot().durationSeconds
            latitudeDeg = lat; longitudeDeg = lon; speedMps = state.speedMps; headingDeg = state.headingDeg
            uncertaintyM = state.horizontalUncertaintyM; localizationMode = state.localizationMode.name
        }
        executor.execute { if (active?.token == current.token || current.trip.id > 0L) { sample.tripId = current.trip.id; store.addSample(sample) } }
    }

    @Synchronized fun stop(wallTimeMs: Long, interrupted: Boolean = false) {
        val current = active ?: return
        active = null
        val summary = current.metrics.snapshot()
        current.trip.apply {
            endWallTimeMs = wallTimeMs; status = if (interrupted) "INTERRUPTED" else "COMPLETED"
            distanceM = summary.distanceM; durationSeconds = summary.durationSeconds
            averageSpeedMps = summary.averageSpeedMps; maximumSpeedMps = summary.maximumSpeedMps
            gnssLossEvents = summary.gnssLossEvents; gnssActiveDurationSeconds = summary.gnssActiveDurationSeconds
            idrDurationSeconds = summary.idrDurationSeconds; longestIdrIntervalSeconds = summary.longestIdrIntervalSeconds
            averageUncertaintyM = summary.averageUncertaintyM; maximumUncertaintyM = summary.maximumUncertaintyM
            gruAssistanceUsed = summary.gruAssistanceUsed
        }
        executor.execute { store.update(current.trip) }
    }

    fun isRecording(): Boolean = active != null

    companion object { private const val SAMPLE_PERIOD_NS = 1_000_000_000L }
}
