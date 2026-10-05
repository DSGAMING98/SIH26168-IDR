package org.sih26168.idrlogger.ui

import android.animation.Animator
import android.animation.AnimatorListenerAdapter
import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Path
import android.graphics.PathMeasure
import android.graphics.RadialGradient
import android.graphics.Rect
import android.graphics.Shader
import android.graphics.Typeface
import android.graphics.drawable.Drawable
import android.view.View
import android.view.animation.LinearInterpolator
import org.sih26168.idrlogger.R
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.sin

internal class NavGhostSplashView(context: Context) : View(context) {
    private val density = resources.displayMetrics.density
    private val backgroundPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val atmospherePaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val gridPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.argb(18, 74, 216, 181)
        strokeWidth = density
    }
    private val routePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
    }
    private val sparkPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textAlign = Paint.Align.CENTER
        typeface = Typeface.create("sans-serif", Typeface.NORMAL)
    }
    private val titlePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textAlign = Paint.Align.CENTER
        typeface = Typeface.create("sans-serif", Typeface.BOLD)
    }
    private val route = Path()
    private val routeSegment = Path()
    private val pathMeasure = PathMeasure()
    private val sparkPosition = FloatArray(2)
    private val logo: Drawable = context.getDrawable(R.drawable.ic_navghost_mark)!!.mutate()
    private var animator: ValueAnimator? = null
    private var progress = 0f
    private var routeLength = 0f

    init {
        setBackgroundColor(NAVY)
        importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_NO
    }

    fun start(reducedMotion: Boolean, onFinished: () -> Unit) {
        animator?.cancel()
        animator = ValueAnimator.ofFloat(0f, 1f).apply {
            duration = SplashAnimationSpec.durationMillis(reducedMotion)
            interpolator = LinearInterpolator()
            addUpdateListener {
                progress = it.animatedValue as Float
                invalidate()
            }
            addListener(object : AnimatorListenerAdapter() {
                private var cancelled = false

                override fun onAnimationCancel(animation: Animator) {
                    cancelled = true
                }

                override fun onAnimationEnd(animation: Animator) {
                    if (!cancelled) onFinished()
                }
            })
            start()
        }
    }

    override fun onDetachedFromWindow() {
        animator?.cancel()
        animator = null
        super.onDetachedFromWindow()
    }

    override fun onSizeChanged(width: Int, height: Int, oldWidth: Int, oldHeight: Int) {
        val centerX = width / 2f
        val centerY = height * 0.40f
        val span = min(width, height) * 0.30f
        route.reset()
        route.moveTo(centerX - span * 0.92f, centerY + span * 0.38f)
        route.cubicTo(
            centerX - span * 0.75f, centerY - span * 0.72f,
            centerX + span * 0.02f, centerY - span * 0.80f,
            centerX + span * 0.22f, centerY - span * 0.20f
        )
        route.cubicTo(
            centerX + span * 0.34f, centerY + span * 0.13f,
            centerX + span * 0.70f, centerY + span * 0.14f,
            centerX + span * 0.93f, centerY + span * 0.44f
        )
        pathMeasure.setPath(route, false)
        routeLength = pathMeasure.length
        backgroundPaint.shader = LinearGradient(
            0f, 0f, width.toFloat(), height.toFloat(),
            intArrayOf(Color.rgb(3, 9, 16), NAVY, Color.rgb(5, 22, 31)),
            floatArrayOf(0f, 0.56f, 1f), Shader.TileMode.CLAMP
        )
        atmospherePaint.shader = RadialGradient(
            centerX, centerY, span * 1.55f,
            intArrayOf(Color.argb(82, 25, 155, 177), Color.argb(22, 74, 216, 181), Color.TRANSPARENT),
            floatArrayOf(0f, 0.46f, 1f), Shader.TileMode.CLAMP
        )
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        canvas.drawRect(0f, 0f, width.toFloat(), height.toFloat(), backgroundPaint)
        drawAtmosphere(canvas)
        drawGrid(canvas)
        drawSignalRoute(canvas)
        drawLogo(canvas)
        drawBrand(canvas)
        drawEdgeFade(canvas)
    }

    private fun drawAtmosphere(canvas: Canvas) {
        val reveal = SplashAnimationSpec.smooth(SplashAnimationSpec.phase(progress, 0f, 0.42f))
        atmospherePaint.alpha = (150 * reveal).toInt()
        canvas.drawCircle(width / 2f, height * 0.40f, min(width, height) * 0.46f, atmospherePaint)
    }

    private fun drawGrid(canvas: Canvas) {
        val alpha = (20 * SplashAnimationSpec.phase(progress, 0.08f, 0.50f) * (1f - SplashAnimationSpec.phase(progress, 0.72f, 1f))).toInt()
        gridPaint.alpha = alpha
        val spacing = 44f * density
        var x = (width / 2f) % spacing
        while (x < width) { canvas.drawLine(x, 0f, x, height.toFloat(), gridPaint); x += spacing }
        var y = (height * 0.40f) % spacing
        while (y < height) { canvas.drawLine(0f, y, width.toFloat(), y, gridPaint); y += spacing }
    }

    private fun drawSignalRoute(canvas: Canvas) {
        val routeProgress = SplashAnimationSpec.smooth(SplashAnimationSpec.phase(progress, 0.05f, 0.53f))
        if (routeProgress <= 0f || routeLength <= 0f) return
        routeSegment.reset()
        pathMeasure.getSegment(0f, routeLength * routeProgress, routeSegment, true)
        routePaint.shader = LinearGradient(
            0f, height * 0.25f, width.toFloat(), height * 0.58f,
            intArrayOf(CYAN, TEAL, Color.WHITE), null, Shader.TileMode.CLAMP
        )
        routePaint.alpha = (220 * (1f - 0.68f * SplashAnimationSpec.phase(progress, 0.58f, 0.92f))).toInt()
        routePaint.strokeWidth = 14f * density
        canvas.drawPath(routeSegment, routePaint)
        routePaint.alpha = 245
        routePaint.strokeWidth = 2.2f * density
        canvas.drawPath(routeSegment, routePaint)

        pathMeasure.getPosTan(routeLength * routeProgress, sparkPosition, null)
        val pulse = 0.86f + 0.14f * sin(progress * 48f)
        sparkPaint.color = Color.argb(46, 55, 220, 232)
        canvas.drawCircle(sparkPosition[0], sparkPosition[1], 27f * density * pulse, sparkPaint)
        sparkPaint.color = Color.argb(130, 110, 241, 247)
        canvas.drawCircle(sparkPosition[0], sparkPosition[1], 12f * density * pulse, sparkPaint)
        sparkPaint.color = Color.WHITE
        canvas.drawCircle(sparkPosition[0], sparkPosition[1], 3.7f * density, sparkPaint)

        val particleReveal = SplashAnimationSpec.phase(progress, 0.22f, 0.68f)
        repeat(9) { index ->
            val distance = routeLength * (routeProgress - index * 0.032f).coerceIn(0f, 1f)
            pathMeasure.getPosTan(distance, sparkPosition, null)
            val angle = index * 1.73f
            val scatter = index * 1.2f * density
            val px = sparkPosition[0] + cos(angle) * scatter
            val py = sparkPosition[1] + sin(angle) * scatter
            sparkPaint.color = Color.argb(((115 - index * 10) * particleReveal).toInt().coerceAtLeast(0), 74, 216, 229)
            canvas.drawCircle(px, py, (3.1f - index * 0.20f).coerceAtLeast(1f) * density, sparkPaint)
        }
    }

    private fun drawLogo(canvas: Canvas) {
        val reveal = SplashAnimationSpec.smooth(SplashAnimationSpec.phase(progress, 0.28f, 0.66f))
        if (reveal <= 0f) return
        val centerX = width / 2f
        val centerY = height * 0.40f
        val size = min(width, height) * (0.27f + 0.025f * reveal)
        sparkPaint.style = Paint.Style.STROKE
        sparkPaint.strokeWidth = 2f * density
        sparkPaint.color = Color.argb((75 * reveal).toInt(), 55, 220, 232)
        canvas.drawCircle(centerX, centerY + size * 0.43f, size * 0.26f, sparkPaint)
        sparkPaint.color = Color.argb((30 * reveal).toInt(), 55, 220, 232)
        canvas.drawCircle(centerX, centerY + size * 0.43f, size * 0.38f, sparkPaint)
        sparkPaint.style = Paint.Style.FILL

        val half = size / 2f
        logo.bounds = Rect(
            (centerX - half).toInt(), (centerY - half).toInt(),
            (centerX + half).toInt(), (centerY + half).toInt()
        )
        logo.alpha = (255 * reveal).toInt()
        logo.draw(canvas)
    }

    private fun drawBrand(canvas: Canvas) {
        val titleReveal = SplashAnimationSpec.smooth(SplashAnimationSpec.phase(progress, 0.52f, 0.76f))
        val taglineReveal = SplashAnimationSpec.smooth(SplashAnimationSpec.phase(progress, 0.65f, 0.84f))
        val centerX = width / 2f
        val titleY = height * 0.66f
        titlePaint.textSize = 42f * density
        titlePaint.color = Color.argb((255 * titleReveal).toInt(), 247, 250, 252)
        canvas.drawText("NavGhost", centerX, titleY + (1f - titleReveal) * 14f * density, titlePaint)

        textPaint.textSize = 13f * density
        textPaint.typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
        textPaint.color = Color.argb((235 * taglineReveal).toInt(), 74, 216, 181)
        canvas.drawText(
            context.getString(R.string.splash_tagline).uppercase(),
            centerX, titleY + 39f * density + (1f - taglineReveal) * 8f * density, textPaint
        )
    }

    private fun drawEdgeFade(canvas: Canvas) {
        val fade = SplashAnimationSpec.phase(progress, 0.90f, 1f)
        if (fade <= 0f) return
        sparkPaint.color = Color.argb((255 * fade).toInt(), 6, 13, 22)
        canvas.drawRect(0f, 0f, width.toFloat(), height.toFloat(), sparkPaint)
    }

    companion object {
        private const val NAVY = 0xFF060D16.toInt()
        private const val CYAN = 0xFF37DCE8.toInt()
        private const val TEAL = 0xFF4AD8B5.toInt()
    }
}
