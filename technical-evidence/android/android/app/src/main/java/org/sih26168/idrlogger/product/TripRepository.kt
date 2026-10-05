package org.sih26168.idrlogger.product

import android.content.Context
import java.util.concurrent.Executors

class TripRepository(context: Context) {
    private val dao = NavGhostDatabase.get(context).tripDao()
    private val executor = Executors.newSingleThreadExecutor()
    fun trips(callback: (List<TripEntity>) -> Unit) = executor.execute { callback(dao.allTrips()) }
    fun trip(id: Long, callback: (TripEntity?, List<TripSampleEntity>) -> Unit) = executor.execute {
        callback(dao.trip(id), dao.samples(id))
    }
    fun delete(trip: TripEntity, callback: () -> Unit) = executor.execute { dao.deleteTrip(trip); callback() }
}

data class InsightsSummary(
    val tripCount: Int,
    val totalDistanceM: Double,
    val totalDurationSeconds: Double,
    val averageSpeedMps: Double,
    val maximumSpeedMps: Double,
    val gnssLossEvents: Int,
    val totalIdrSeconds: Double,
    val averageUncertaintyM: Double?,
    val longestTripDistanceM: Double,
    val longestIdrIntervalSeconds: Double,
)

object InsightsCalculator {
    fun calculate(trips: List<TripEntity>): InsightsSummary {
        val complete = trips.filter { it.status == "COMPLETED" || it.status == "INTERRUPTED" }
        val duration = complete.sumOf { it.durationSeconds.coerceAtLeast(0.0) }
        val weightedSpeed = complete.sumOf { it.averageSpeedMps.coerceAtLeast(0.0) * it.durationSeconds.coerceAtLeast(0.0) }
        val withUncertainty = complete.filter { it.averageUncertaintyM != null }
        return InsightsSummary(complete.size, complete.sumOf { it.distanceM.coerceAtLeast(0.0) }, duration,
            if (duration > 0.0) weightedSpeed / duration else 0.0,
            complete.maxOfOrNull { it.maximumSpeedMps } ?: 0.0,
            complete.sumOf { it.gnssLossEvents.coerceAtLeast(0) }, complete.sumOf { it.idrDurationSeconds.coerceAtLeast(0.0) },
            withUncertainty.takeIf { it.isNotEmpty() }?.mapNotNull { it.averageUncertaintyM }?.average(),
            complete.maxOfOrNull { it.distanceM } ?: 0.0, complete.maxOfOrNull { it.longestIdrIntervalSeconds } ?: 0.0)
    }
}
