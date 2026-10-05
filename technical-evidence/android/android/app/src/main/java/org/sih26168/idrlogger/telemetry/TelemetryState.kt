package org.sih26168.idrlogger.telemetry

enum class TelemetryConnectionState { DISABLED, DISCONNECTED, CONNECTING, CONNECTED, RETRYING, SHUTDOWN }

data class TelemetryStatus(
    val state: TelemetryConnectionState = TelemetryConnectionState.DISABLED,
    val sessionId: String? = null,
    val rateHz: Int = 5,
    val offeredMessages: Long = 0,
    val sentMessages: Long = 0,
    val coalescedMessages: Long = 0,
    val droppedMessages: Long = 0,
    val errorCount: Long = 0,
    val reconnectAttempts: Int = 0,
    val lastSendTimestampNs: Long? = null,
    val lastError: String? = null,
    val queuedMessages: Int = 0,
    val queuedBytes: Long = 0,
)

internal class TelemetryRateLimiter {
    private var lastSendNs: Long? = null
    fun ready(nowNs: Long, rateHz: Int): Boolean = lastSendNs?.let {
        nowNs - it >= 1_000_000_000L / rateHz.coerceIn(1, 10)
    } ?: true
    fun sent(nowNs: Long) { lastSendNs = nowNs }
    fun reset() { lastSendNs = null }
}
