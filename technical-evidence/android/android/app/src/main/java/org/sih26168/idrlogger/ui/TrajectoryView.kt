package org.sih26168.idrlogger.ui

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.DashPathEffect
import android.graphics.Paint
import android.graphics.Path
import android.view.View
import kotlin.math.ceil
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.sin
import org.sih26168.idrlogger.engine.LocalizationMode
import org.sih26168.idrlogger.engine.NavigationSnapshot
import org.sih26168.idrlogger.engine.TrajectoryPoint
import org.sih26168.idrlogger.map.LocalEnuMapProvider
import org.sih26168.idrlogger.map.MapPresentation

class TrajectoryView(context: Context) : View(context) {
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private var snapshot = NavigationSnapshot()
    private var mode = ViewportMode.FOLLOW_CURRENT
    private var comparison: List<TrajectoryPoint> = emptyList()
    private var comparisonLabel: String? = null
    private var secondaryComparison: List<TrajectoryPoint> = emptyList()
    private var secondaryComparisonLabel: String? = null
    private var mapPresentation: MapPresentation = LocalEnuMapProvider().presentation()

    init {
        setBackgroundColor(BACKGROUND)
        contentDescription = "Local offline trajectory with current position, heading, uncertainty, and localization state"
    }

    fun show(
        value: NavigationSnapshot,
        viewportMode: ViewportMode = mode,
        comparisonPoints: List<TrajectoryPoint> = emptyList(),
        comparisonName: String? = null,
        mapContext: MapPresentation = mapPresentation,
        secondaryComparisonPoints: List<TrajectoryPoint> = emptyList(),
        secondaryComparisonName: String? = null,
    ) {
        snapshot = value; mode = viewportMode; comparison = comparisonPoints; comparisonLabel = comparisonName; mapPresentation = mapContext
        secondaryComparison = secondaryComparisonPoints; secondaryComparisonLabel = secondaryComparisonName; invalidate()
    }

    fun recenter() { mode = ViewportMode.FOLLOW_CURRENT; invalidate() }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val widthF = width.toFloat(); val heightF = height.toFloat()
        if (widthF <= 0f || heightF <= 0f) return
        canvas.drawColor(BACKGROUND)
        val state = snapshot.state
        val points = snapshot.trajectory.filter { it.eastM.isFinite() && it.northM.isFinite() }
        val viewport = TrajectoryViewportCalculator.calculate(points + comparison + secondaryComparison, state.eastM, state.northM, mode)
        val margin = 30f
        val scale = min((widthF - 2 * margin) / viewport.spanEastM, (heightF - 2 * margin) / viewport.spanNorthM).coerceAtLeast(0.001)
        fun x(east: Double) = (widthF / 2f + (east - viewport.centerEastM) * scale).toFloat()
        fun y(north: Double) = (heightF / 2f - (north - viewport.centerNorthM) * scale).toFloat()
        drawGrid(canvas, viewport, margin, widthF, heightF, ::x, ::y)
        if (comparison.size >= 2) {
            paint.style = Paint.Style.STROKE; paint.strokeWidth = 3f; paint.color = Color.rgb(214, 220, 232)
            paint.pathEffect = DashPathEffect(floatArrayOf(12f, 8f), 0f)
            val path = Path().apply { moveTo(x(comparison[0].eastM), y(comparison[0].northM)); comparison.drop(1).forEach { lineTo(x(it.eastM), y(it.northM)) } }
            canvas.drawPath(path, paint); paint.pathEffect = null
        }
        if (secondaryComparison.size >= 2) {
            paint.style = Paint.Style.STROKE; paint.strokeWidth = 3f; paint.color = Color.rgb(255, 174, 72)
            paint.pathEffect = DashPathEffect(floatArrayOf(5f, 7f), 0f)
            val path = Path().apply { moveTo(x(secondaryComparison[0].eastM), y(secondaryComparison[0].northM)); secondaryComparison.drop(1).forEach { lineTo(x(it.eastM), y(it.northM)) } }
            canvas.drawPath(path, paint); paint.pathEffect = null
        }
        if (points.size >= 2) {
            paint.style = Paint.Style.STROKE; paint.strokeWidth = 5f; paint.strokeCap = Paint.Cap.ROUND
            for (index in 1 until points.size) {
                paint.color = colorFor(points[index].localizationMode)
                canvas.drawLine(x(points[index - 1].eastM), y(points[index - 1].northM), x(points[index].eastM), y(points[index].northM), paint)
            }
        }
        val currentX = x(state.eastM); val currentY = y(state.northM)
        val uncertaintyPx = ((state.horizontalUncertaintyM ?: 0.0) * scale).toFloat().coerceIn(0f, min(widthF, heightF) * 0.42f)
        if (uncertaintyPx > 1f) {
            paint.style = Paint.Style.FILL; paint.color = Color.argb(45, 88, 166, 255); canvas.drawCircle(currentX, currentY, uncertaintyPx, paint)
            paint.style = Paint.Style.STROKE; paint.strokeWidth = 2f; paint.color = Color.argb(150, 88, 166, 255); canvas.drawCircle(currentX, currentY, uncertaintyPx, paint)
        }
        paint.style = Paint.Style.FILL; paint.color = colorFor(state.localizationMode); canvas.drawCircle(currentX, currentY, 10f, paint)
        val heading = Math.toRadians(state.headingDeg)
        paint.style = Paint.Style.STROKE; paint.strokeWidth = 5f; paint.strokeCap = Paint.Cap.ROUND
        canvas.drawLine(currentX, currentY, currentX + (sin(heading) * 28).toFloat(), currentY - (cos(heading) * 28).toFloat(), paint)
        drawLabels(canvas, viewport, widthF, heightF)
    }

    private fun drawGrid(canvas: Canvas, viewport: TrajectoryViewport, margin: Float, widthF: Float, heightF: Float, x: (Double) -> Float, y: (Double) -> Float) {
        paint.style = Paint.Style.STROKE; paint.strokeWidth = 1f; paint.color = GRID
        val minE = viewport.centerEastM - viewport.spanEastM / 2; val maxE = viewport.centerEastM + viewport.spanEastM / 2
        val minN = viewport.centerNorthM - viewport.spanNorthM / 2; val maxN = viewport.centerNorthM + viewport.spanNorthM / 2
        var e = ceil(minE / viewport.gridSpacingM) * viewport.gridSpacingM
        while (e <= maxE) { canvas.drawLine(x(e), margin, x(e), heightF - margin, paint); e += viewport.gridSpacingM }
        var n = ceil(minN / viewport.gridSpacingM) * viewport.gridSpacingM
        while (n <= maxN) { canvas.drawLine(margin, y(n), widthF - margin, y(n), paint); n += viewport.gridSpacingM }
    }

    private fun drawLabels(canvas: Canvas, viewport: TrajectoryViewport, widthF: Float, heightF: Float) {
        paint.style = Paint.Style.FILL; paint.color = TEXT_MUTED; paint.textSize = 17f; paint.isFakeBoldText = true
        canvas.drawText(mapPresentation.primaryLabel, 16f, 25f, paint)
        comparisonLabel?.let { canvas.drawText("COMPARE • $it", 16f, 48f, paint) }
        secondaryComparisonLabel?.let { canvas.drawText("+ $it", 16f, 70f, paint) }
        canvas.drawText("N ↑", widthF - 42f, 25f, paint)
        paint.isFakeBoldText = false; paint.textSize = 16f
        canvas.drawText("${viewport.gridSpacingM.toInt()} m grid", 16f, heightF - 12f, paint)
        canvas.drawText("GNSS • IDR • RECOVERY", widthF - 190f, heightF - 12f, paint)
    }

    private fun colorFor(mode: LocalizationMode): Int = when (mode) {
        LocalizationMode.GNSS_ACTIVE -> Color.rgb(55, 205, 165)
        LocalizationMode.IDR_ACTIVE -> Color.rgb(255, 174, 72)
        LocalizationMode.GNSS_VERIFYING, LocalizationMode.GNSS_RECOVERING -> Color.rgb(150, 126, 255)
        LocalizationMode.ERROR -> Color.rgb(255, 92, 105)
        LocalizationMode.CALIBRATION_REQUIRED -> Color.rgb(255, 194, 92)
        else -> Color.rgb(125, 147, 165)
    }

    companion object {
        private val BACKGROUND = Color.rgb(11, 21, 33)
        private val GRID = Color.rgb(29, 46, 63)
        private val TEXT_MUTED = Color.rgb(151, 171, 190)
    }
}
