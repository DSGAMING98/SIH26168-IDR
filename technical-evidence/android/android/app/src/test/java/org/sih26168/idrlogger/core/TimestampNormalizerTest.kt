package org.sih26168.idrlogger.core

import org.junit.Assert.assertEquals
import org.junit.Test

class TimestampNormalizerTest {
    @Test
    fun normalizesMonotonicTimeAndMapsDiagnosticWallClock() {
        val normalizer = TimestampNormalizer(10_000_000_000L, 1_700_000_000_000L)

        assertEquals(1.25, normalizer.elapsedSeconds(11_250_000_000L), 1e-12)
        assertEquals("2023-11-14T22:13:21.250Z", normalizer.wallClockUtc(11_250_000_000L))
    }

    @Test
    fun preservesPreOriginAgeForCachedLocation() {
        val normalizer = TimestampNormalizer(10_000_000_000L, 1_700_000_000_000L)

        assertEquals(-1.0, normalizer.elapsedSeconds(9_000_000_000L), 1e-12)
    }
}
