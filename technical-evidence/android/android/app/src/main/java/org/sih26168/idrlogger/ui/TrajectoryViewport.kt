package org.sih26168.idrlogger.ui

import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.max
import kotlin.math.sqrt
import org.sih26168.idrlogger.engine.LocalizationMode
import org.sih26168.idrlogger.engine.TrajectoryPoint

enum class ViewportMode { FOLLOW_CURRENT, AUTO_FIT }

data class TrajectoryViewport(
    val centerEastM: Double,
    val centerNorthM: Double,
    val spanEastM: Double,
    val spanNorthM: Double,
    val gridSpacingM: Double,
)

object TrajectoryViewportCalculator {
    fun calculate(points: List<TrajectoryPoint>, currentEastM: Double, currentNorthM: Double, mode: ViewportMode): TrajectoryViewport {
        val finite = points.filter { it.eastM.isFinite() && it.northM.isFinite() }.toMutableList()
        if (currentEastM.isFinite() && currentNorthM.isFinite()) {
            finite += TrajectoryPoint(currentEastM, currentNorthM, points.lastOrNull()?.localizationMode ?: LocalizationMode.WAITING_FOR_GNSS)
        }
        if (finite.isEmpty()) return TrajectoryViewport(0.0, 0.0, 40.0, 40.0, 10.0)
        if (mode == ViewportMode.FOLLOW_CURRENT) {
            val radii = finite.takeLast(300).map {
                sqrt((it.eastM - currentEastM) * (it.eastM - currentEastM) + (it.northM - currentNorthM) * (it.northM - currentNorthM))
            }.sorted()
            val localRadius = radii[(radii.size * 0.90).toInt().coerceIn(0, radii.lastIndex)].coerceIn(20.0, 180.0)
            val span = max(40.0, localRadius * 2.3)
            return TrajectoryViewport(currentEastM, currentNorthM, span, span, gridFor(span))
        }
        val robust = rejectSingleExtremeOutliers(finite)
        val minE = robust.minOf { it.eastM }; val maxE = robust.maxOf { it.eastM }
        val minN = robust.minOf { it.northM }; val maxN = robust.maxOf { it.northM }
        val spanE = max(40.0, (maxE - minE) * 1.18)
        val spanN = max(40.0, (maxN - minN) * 1.18)
        return TrajectoryViewport((minE + maxE) / 2.0, (minN + maxN) / 2.0, spanE, spanN, gridFor(max(spanE, spanN)))
    }

    private fun rejectSingleExtremeOutliers(points: List<TrajectoryPoint>): List<TrajectoryPoint> {
        if (points.size < 8) return points
        val eastMedian = median(points.map { it.eastM }); val northMedian = median(points.map { it.northM })
        val distances = points.map { sqrt((it.eastM - eastMedian) * (it.eastM - eastMedian) + (it.northM - northMedian) * (it.northM - northMedian)) }
        val distanceMedian = median(distances)
        val mad = median(distances.map { abs(it - distanceMedian) }).coerceAtLeast(1.0)
        val threshold = max(500.0, distanceMedian + 20.0 * mad)
        val retained = points.zip(distances).filter { it.second <= threshold }.map { it.first }
        return if (retained.size >= points.size - max(1, points.size / 100)) retained else points
    }

    private fun median(values: List<Double>): Double {
        val sorted = values.sorted(); val middle = sorted.size / 2
        return if (sorted.size % 2 == 0) (sorted[middle - 1] + sorted[middle]) / 2.0 else sorted[middle]
    }

    private fun gridFor(spanM: Double): Double {
        val candidates = doubleArrayOf(5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 500.0)
        return candidates.firstOrNull { spanM / it <= 8.0 } ?: ceil(spanM / 8.0 / 500.0) * 500.0
    }
}
