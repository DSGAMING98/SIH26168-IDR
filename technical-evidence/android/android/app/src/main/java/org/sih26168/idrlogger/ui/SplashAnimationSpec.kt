package org.sih26168.idrlogger.ui

internal object SplashAnimationSpec {
    const val STANDARD_DURATION_MS = 2_250L
    const val REDUCED_MOTION_DURATION_MS = 360L

    fun durationMillis(reducedMotion: Boolean): Long =
        if (reducedMotion) REDUCED_MOTION_DURATION_MS else STANDARD_DURATION_MS

    fun phase(progress: Float, start: Float, end: Float): Float {
        require(end > start) { "phase end must be greater than start" }
        return ((progress - start) / (end - start)).coerceIn(0f, 1f)
    }

    fun smooth(value: Float): Float {
        val x = value.coerceIn(0f, 1f)
        return x * x * (3f - 2f * x)
    }
}
