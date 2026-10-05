package org.sih26168.idrlogger.product

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.view.View

/** Lightweight canvas chart for downsampled product data; never touches the estimator loop. */
class MiniChartView(context: Context) : View(context) {
    private var series: List<Double> = emptyList()
    private var accent = Color.rgb(74, 216, 181)
    private val line = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; strokeWidth = resources.displayMetrics.density * 2.5f; strokeCap = Paint.Cap.ROUND }
    private val grid = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.argb(45, 150, 180, 200); strokeWidth = resources.displayMetrics.density }
    private val path = Path()

    fun setSeries(values: List<Double>, color: Int = accent) {
        series = if (values.size <= MAX_POINTS) values else values.filterIndexed { index, _ -> index % ((values.size + MAX_POINTS - 1) / MAX_POINTS) == 0 }
        accent = color; invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val p = resources.displayMetrics.density * 8f
        repeat(3) { i -> val y = p + (height - 2 * p) * i / 2f; canvas.drawLine(p, y, width - p, y, grid) }
        if (series.size < 2) return
        val min = series.minOrNull() ?: 0.0; val max = series.maxOrNull() ?: min
        val span = (max - min).coerceAtLeast(1e-6)
        path.reset()
        series.forEachIndexed { i, value ->
            val x = p + (width - 2 * p) * i / (series.size - 1f)
            val y = height - p - ((value - min) / span * (height - 2 * p)).toFloat()
            if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
        }
        line.color = accent; canvas.drawPath(path, line)
    }

    companion object { const val MAX_POINTS = 180 }
}
