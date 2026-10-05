package org.sih26168.idrlogger.core

import java.time.Instant

class TimestampNormalizer(
    private val sessionOriginNs: Long,
    private val sessionStartWallClockMs: Long,
) {
    init {
        require(sessionOriginNs >= 0L) { "Session monotonic origin cannot be negative." }
        require(sessionStartWallClockMs >= 0L) { "Session wall-clock origin cannot be negative." }
    }

    fun elapsedSeconds(monotonicTimestampNs: Long): Double {
        return (monotonicTimestampNs - sessionOriginNs) / 1_000_000_000.0
    }

    fun wallClockUtc(monotonicTimestampNs: Long): String {
        val elapsedMs = (monotonicTimestampNs - sessionOriginNs) / 1_000_000L
        return Instant.ofEpochMilli(sessionStartWallClockMs + elapsedMs).toString()
    }
}
