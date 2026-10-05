package org.sih26168.idrlogger.telemetry

import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference
import org.sih26168.idrlogger.engine.NavigationState

/** Transport callbacks are notifications only. Server messages have NO navigation/control handler. */
internal interface TelemetrySocket {
    fun send(text: String): Boolean
    fun queuedBytes(): Long
    fun cancel()
}
internal interface TelemetryTransport {
    fun open(endpoint: String, onOpen: () -> Unit, onFailure: () -> Unit): TelemetrySocket
    fun shutdown()
}

/**
 * One-way observer. publish() only swaps one immutable snapshot; no formatting, socket calls,
 * locks, coroutine launches, or unbounded jobs execute on the normalized sensor thread.
 * All transport/JSON work is performed by one bounded-rate daemon worker.
 */
class TelemetryClient internal constructor(
    private val transport: TelemetryTransport,
    private val clock: () -> Long = System::nanoTime,
    automaticWorker: Boolean = true,
) {
    constructor() : this(OkHttpTelemetryTransport())
    private data class Session(val id: String)
    private data class Pending(val session: Session, val state: NavigationState, val diagnostics: TelemetryDiagnostics)
    private data class Event(val generation: Long, val opened: Boolean)
    private val executor = if (automaticWorker) Executors.newSingleThreadScheduledExecutor { job ->
        Thread(job, "NavGhostTelemetry").apply { isDaemon = true }
    } else null
    private val config = AtomicReference(TelemetryConfig())
    private val session = AtomicReference<Session?>(null)
    private val latest = AtomicReference<Pending?>(null)
    private val event = AtomicReference<Event?>(null)
    private val offered = AtomicLong()
    private val coalesced = AtomicLong()
    private val dropped = AtomicLong()
    @Volatile private var requested = false
    @Volatile private var closing = false
    @Volatile private var view = TelemetryStatus()
    private var activeConfig = TelemetryConfig()
    private var activeSession: Session? = null
    private var socket: TelemetrySocket? = null
    @Volatile private var generation = 0L
    private var nextRetryNs = 0L
    private var connectingSinceNs = 0L
    private var sequence = 0L
    private var cleaned = false
    private val limiter = TelemetryRateLimiter()

    init { executor?.scheduleWithFixedDelay({ pump() }, 0, 20, TimeUnit.MILLISECONDS) }

    fun configuration(): TelemetryConfig = config.get()
    fun configure(value: TelemetryConfig): String? {
        val normalized = value.normalized()
        normalized.validationError()?.let { return it }
        config.set(normalized)
        requested = normalized.enabled
        return null
    }
    fun connect() { if (config.get().enabled && !closing) requested = true }
    fun disconnect() { requested = false; latest.set(null) }
    fun startSession(): String {
        val next = Session(UUID.randomUUID().toString())
        latest.set(null); offered.set(0); coalesced.set(0); dropped.set(0)
        session.set(next)
        requested = config.get().enabled
        return next.id
    }
    fun stopSession() { requested = false; session.set(null); latest.set(null) }
    fun publish(state: NavigationState, diagnostics: TelemetryDiagnostics, producerSessionId: String?) {
        if (!config.get().enabled || !requested || closing) return
        val current = session.get() ?: return
        if (producerSessionId != current.id) return
        offered.incrementAndGet()
        if (latest.getAndSet(Pending(current, state, diagnostics)) != null) coalesced.incrementAndGet()
    }
    fun status(): TelemetryStatus = view.copy(
        sessionId = session.get()?.id, rateHz = config.get().rateHz,
        offeredMessages = offered.get(), coalescedMessages = coalesced.get(),
        droppedMessages = dropped.get(), queuedMessages = if (latest.get() == null) 0 else 1,
    )
    fun shutdown() { closing = true; requested = false; latest.set(null) }

    /** Also drives deterministic JVM tests without timing sleeps or real sockets. */
    internal fun pump() {
        try { update() } catch (_: Exception) {
            fail(clock(), "Telemetry unavailable; navigation unaffected")
        }
    }
    private fun cancelSocket() {
        generation++
        socket?.cancel(); socket = null; event.set(null)
    }
    private fun update() {
        if (closing) {
            if (!cleaned) {
                cleaned = true; cancelSocket(); transport.shutdown()
                view = view.copy(state = TelemetryConnectionState.SHUTDOWN, queuedBytes = 0)
                executor?.shutdown()
            }
            return
        }
        val now = clock()
        val setting = config.get()
        val recording = session.get()
        if (recording !== activeSession) {
            cancelSocket(); activeSession = recording; sequence = 0; limiter.reset(); nextRetryNs = 0
            view = if (recording == null) view.copy(state = TelemetryConnectionState.DISCONNECTED) else TelemetryStatus(rateHz = setting.rateHz)
        }
        if (setting != activeConfig) {
            cancelSocket(); activeConfig = setting; nextRetryNs = 0; limiter.reset()
            view = view.copy(state = TelemetryConnectionState.DISCONNECTED, lastError = null)
        }
        if (!setting.enabled || !requested) {
            if (socket != null) cancelSocket()
            latest.set(null)
            view = view.copy(state = if (setting.enabled) TelemetryConnectionState.DISCONNECTED else TelemetryConnectionState.DISABLED, queuedBytes = 0)
            return
        }
        event.getAndSet(null)?.takeIf { it.generation == generation }?.let {
            if (it.opened) view = view.copy(state = TelemetryConnectionState.CONNECTED, lastError = null)
            else fail(now, "Connection unavailable; navigation unaffected")
        }
        if (socket == null && now >= nextRetryNs) {
            val connectionGeneration = ++generation
            connectingSinceNs = now
            view = view.copy(state = TelemetryConnectionState.CONNECTING)
            socket = transport.open(setting.endpoint,
                { offerEvent(connectionGeneration, true) },
                { offerEvent(connectionGeneration, false) })
        }
        if (view.state == TelemetryConnectionState.CONNECTING && now - connectingSinceNs >= CONNECTION_TIMEOUT_NS) {
            fail(now, "Connection timed out; navigation unaffected")
        }
        if (view.state != TelemetryConnectionState.CONNECTED) {
            if (latest.getAndSet(null) != null) dropped.incrementAndGet()
            return
        }
        if (!limiter.ready(now, setting.rateHz)) return
        val pending = latest.getAndSet(null) ?: return
        if (pending.session !== activeSession || pending.session !== session.get()) { dropped.incrementAndGet(); return }
        val connection = socket ?: return
        val json = TelemetrySerializer.serialize(TelemetryMessage.fromNavigation(pending.state, pending.diagnostics), pending.session.id, sequence)
        val bytes = json.toByteArray(Charsets.UTF_8).size
        val buffered = connection.queuedBytes()
        if (bytes > MAX_MESSAGE_BYTES || buffered + bytes > MAX_SOCKET_BYTES) {
            dropped.incrementAndGet(); fail(now, "Slow connection; latest updates only"); return
        }
        // Controls may change while the worker formats JSON or consults a transport.
        if (!requested || closing || config.get() != setting || session.get() !== pending.session) {
            dropped.incrementAndGet(); return
        }
        if (!connection.send(json)) { dropped.incrementAndGet(); fail(now, "Send unavailable; navigation unaffected"); return }
        sequence++; limiter.sent(now)
        view = view.copy(sentMessages = view.sentMessages + 1, reconnectAttempts = 0,
            lastSendTimestampNs = now, queuedBytes = connection.queuedBytes(), lastError = null)
    }
    private fun offerEvent(connectionGeneration: Long, opened: Boolean) {
        if (connectionGeneration != generation) return
        event.updateAndGet { previous ->
            if (previous != null && previous.generation > connectionGeneration) previous else Event(connectionGeneration, opened)
        }
    }
    private fun fail(now: Long, message: String) {
        cancelSocket()
        val attempts = (view.reconnectAttempts + 1).coerceAtMost(30)
        nextRetryNs = now + retryDelaySeconds(attempts) * 1_000_000_000L
        view = view.copy(state = TelemetryConnectionState.RETRYING, errorCount = view.errorCount + 1,
            reconnectAttempts = attempts, lastError = message, queuedBytes = 0)
    }
    companion object {
        internal const val MAX_MESSAGE_BYTES = 8_192
        internal const val MAX_SOCKET_BYTES = 32_768L
        private const val CONNECTION_TIMEOUT_NS = 10_000_000_000L
        internal fun retryDelaySeconds(attempt: Int): Long = minOf(30L, 1L shl (attempt - 1).coerceIn(0, 5))
    }
}
