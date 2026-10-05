package org.sih26168.idrlogger.core

import org.sih26168.idrlogger.model.SensorKind
import org.sih26168.idrlogger.model.SensorRateSnapshot
import java.util.EnumMap

class SensorRateTracker {
    private data class Counts(var firstNs: Long = 0L, var lastNs: Long = 0L, var count: Long = 0L)
    private val counts = EnumMap<SensorKind, Counts>(SensorKind::class.java)
    private val normalized = Counts()

    init {
        SensorKind.entries.forEach { counts[it] = Counts() }
    }

    @Synchronized
    fun record(kind: SensorKind, timestampNs: Long) = record(counts.getValue(kind), timestampNs)

    @Synchronized
    fun recordNormalized(timestampNs: Long) = record(normalized, timestampNs)

    @Synchronized
    fun snapshot() = SensorRateSnapshot(
        rate(counts.getValue(SensorKind.ACCELEROMETER)),
        rate(counts.getValue(SensorKind.GYROSCOPE)),
        rate(counts.getValue(SensorKind.MAGNETOMETER)),
        rate(counts.getValue(SensorKind.GRAVITY)),
        rate(counts.getValue(SensorKind.ROTATION_VECTOR)),
        rate(normalized),
    )

    @Synchronized
    fun reset() {
        counts.values.forEach { it.firstNs = 0L; it.lastNs = 0L; it.count = 0L }
        normalized.firstNs = 0L
        normalized.lastNs = 0L
        normalized.count = 0L
    }

    private fun record(value: Counts, timestampNs: Long) {
        if (value.count == 0L) value.firstNs = timestampNs
        if (timestampNs > value.lastNs) value.lastNs = timestampNs
        value.count += 1
    }

    private fun rate(value: Counts): Double {
        if (value.count < 2 || value.lastNs <= value.firstNs) return 0.0
        return (value.count - 1) * 1_000_000_000.0 / (value.lastNs - value.firstNs)
    }
}
