package org.sih26168.idrlogger.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.sih26168.idrlogger.engine.LocalizationMode
import org.sih26168.idrlogger.engine.TrajectoryPoint

class TrajectoryViewportTest {
    @Test fun autoFitRejectsOneExtremeOutlierWithoutHidingNormalTrack() {
        val points = (0..99).map { TrajectoryPoint(it.toDouble(), it * 0.2, LocalizationMode.GNSS_ACTIVE) } +
            TrajectoryPoint(1_000_000.0, -1_000_000.0, LocalizationMode.ERROR)
        val view = TrajectoryViewportCalculator.calculate(points, 99.0, 19.8, ViewportMode.AUTO_FIT)
        assertTrue(view.spanEastM in 100.0..150.0)
        assertTrue(view.spanNorthM in 40.0..60.0)
    }

    @Test fun liveModeFollowsCurrentPositionWithBoundedLocalRadius() {
        val points = listOf(TrajectoryPoint(-10_000.0, 0.0, LocalizationMode.GNSS_ACTIVE), TrajectoryPoint(40.0, 20.0, LocalizationMode.IDR_ACTIVE))
        val view = TrajectoryViewportCalculator.calculate(points, 42.0, 21.0, ViewportMode.FOLLOW_CURRENT)
        assertEquals(42.0, view.centerEastM, 0.0); assertEquals(21.0, view.centerNorthM, 0.0)
        assertTrue(view.spanEastM <= 414.0)
    }
}
