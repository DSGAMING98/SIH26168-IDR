package org.sih26168.idrlogger.core

import org.sih26168.idrlogger.model.SensorKind
import org.sih26168.idrlogger.model.TimedSensorValue
import java.util.ArrayDeque
import java.util.EnumMap

class CausalSensorBuffer(private val capacityPerSensor: Int = 256) {
    private val queues = EnumMap<SensorKind, ArrayDeque<TimedSensorValue>>(SensorKind::class.java)

    init {
        require(capacityPerSensor > 1) { "Buffer capacity must exceed one sample." }
        SensorKind.entries.forEach { queues[it] = ArrayDeque() }
    }

    @Synchronized
    fun add(sample: TimedSensorValue): Boolean {
        val queue = queues.getValue(sample.kind)
        val previous = queue.peekLast()
        if (previous != null && sample.monotonicTimestampNs <= previous.monotonicTimestampNs) {
            return false
        }
        queue.addLast(sample)
        while (queue.size > capacityPerSensor) queue.removeFirst()
        return true
    }

    @Synchronized
    fun latestAtOrBefore(kind: SensorKind, timestampNs: Long): TimedSensorValue? {
        return queues.getValue(kind).lastOrNull { it.monotonicTimestampNs <= timestampNs }
    }

    @Synchronized
    fun clear() = queues.values.forEach { it.clear() }
}
