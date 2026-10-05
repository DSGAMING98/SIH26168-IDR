package org.sih26168.idrlogger.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SplashAnimationSpecTest {
    @Test
    fun standardAnimationStaysWithinRequestedStartupWindow() {
        assertTrue(SplashAnimationSpec.STANDARD_DURATION_MS in 1_800L..2_800L)
        assertEquals(SplashAnimationSpec.STANDARD_DURATION_MS, SplashAnimationSpec.durationMillis(false))
    }

    @Test
    fun reducedMotionUsesShortNonAnimatedHandoff() {
        assertTrue(SplashAnimationSpec.REDUCED_MOTION_DURATION_MS < 500L)
        assertEquals(SplashAnimationSpec.REDUCED_MOTION_DURATION_MS, SplashAnimationSpec.durationMillis(true))
    }

    @Test
    fun phasesClampAndEaseDeterministically() {
        assertEquals(0f, SplashAnimationSpec.phase(0.1f, 0.2f, 0.6f), 0f)
        assertEquals(0.5f, SplashAnimationSpec.phase(0.4f, 0.2f, 0.6f), 0.0001f)
        assertEquals(1f, SplashAnimationSpec.phase(0.9f, 0.2f, 0.6f), 0f)
        assertEquals(0.5f, SplashAnimationSpec.smooth(0.5f), 0.0001f)
    }
}
