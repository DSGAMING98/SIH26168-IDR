package org.sih26168.idrlogger.telemetry

import org.junit.Assert.*
import org.junit.Test
import org.sih26168.idrlogger.engine.*
import org.sih26168.idrlogger.model.*

internal class TestSocket(val opened: () -> Unit, val failed: () -> Unit) : TelemetrySocket {
    val messages = mutableListOf<String>()
    var bytes = 0L
    var cancelled = false
    var accepts = true
    var onQueue: (() -> Unit)? = null
    override fun send(text: String): Boolean { if (accepts) messages.add(text); return accepts }
    override fun queuedBytes(): Long { onQueue?.invoke(); return bytes }
    override fun cancel() { cancelled = true }
}
internal class TestTransport : TelemetryTransport {
    val sockets = mutableListOf<TestSocket>()
    var shut = false
    var throwOnOpen = false
    override fun open(endpoint: String, onOpen: () -> Unit, onFailure: () -> Unit): TelemetrySocket {
        if (throwOnOpen) error("simulated transport failure")
        return TestSocket(onOpen, onFailure).also { sockets.add(it) }
    }
    override fun shutdown() { shut = true }
}
private class Rig {
    var now = 1_000_000_000L
    val transport = TestTransport()
    val client = TelemetryClient(transport, { now }, automaticWorker = false)
    var token = ""
    val nav = NavigationState(monotonicTimestampNs = 12345678901234567L,
        latitudeDeg = 12.0, longitudeDeg = 77.0, eastM = 4.0, northM = 6.0,
        speedMps = 5.0, headingDeg = 359.0, localizationMode = LocalizationMode.IDR_ACTIVE)
    val diagnostics = TelemetryDiagnostics(recording = true, gnssStatus = GnssStatus.SIMULATED_BLACKOUT)
    fun start(rate: Int = 5) {
        assertNull(client.configure(TelemetryConfig(true, "ws://localhost:8000/ws/telemetry", rate)))
        token = client.startSession(); client.pump()
        transport.sockets.last().opened(); client.pump()
    }
    fun publish(state: NavigationState = nav) { client.publish(state, diagnostics, token) }
    fun step(ms: Long = 200) { now += ms * 1_000_000; client.pump() }
}

class TelemetryClientTest {
    @Test fun telemetryDisabledByDefaultDoesNotOpenSocket() {
        val r = Rig(); r.token = r.client.startSession(); r.publish(); r.client.pump()
        assertEquals(TelemetryConnectionState.DISABLED, r.client.status().state)
        assertTrue(r.transport.sockets.isEmpty()); assertEquals(0, r.client.status().queuedMessages)
    }
    @Test fun configurationClampsRateAndRejectsUnsafeEndpoints() {
        assertEquals(5, TelemetryConfig().rateHz)
        assertEquals(10, TelemetryConfig(rateHz = 99).normalized().rateHz)
        assertEquals(1, TelemetryConfig(rateHz = -1).normalized().rateHz)
        for (url in listOf("http://localhost:8000/ws/telemetry", "ws://example.com/ws/telemetry",
                "ws://user:password@localhost/ws/telemetry", "ws://localhost/ws/telemetry?key=x",
                "ws://localhost/other", "ws://localhost:99999/ws/telemetry")) {
            assertNotNull(url, TelemetryConfig(true, url).validationError())
        }
        assertNull(TelemetryConfig(true, "wss://example.com/ws/telemetry").validationError())
    }
    @Test fun blackoutSerializationCannotLeakPhysicalGnssOrReference() {
        val r = Rig()
        val text = TelemetrySerializer.serialize(TelemetryMessage.fromNavigation(r.nav, r.diagnostics), "safe-session", 3)
        assertTrue(text.contains("\"latitude\":12.0"))
        assertTrue(text.contains("\"gnss_state\":\"SIMULATED_BLACKOUT\""))
        for (forbidden in listOf("PhysicalGnssFix", "raw_gnss", "vbox", "reference", "accelerometer_x", "api_key", "sessionDirectory", "bearing_deg")) {
            assertFalse(forbidden, text.contains(forbidden, ignoreCase = true))
        }
        assertTrue(text.contains("\"timestamp_ns\":\"12345678901234567\""))
        assertTrue(text.contains("\"sequence\":3"))
    }
    @Test fun unavailableMeasurementsRemainNullAndBatteryIsAnInteger() {
        val r = Rig()
        val text = TelemetrySerializer.serialize(TelemetryMessage.fromNavigation(NavigationState(), TelemetryDiagnostics()), "s", 0)
        assertTrue(text.contains("\"latitude\":null")); assertTrue(text.contains("\"heading_deg\":null"))
        assertTrue(text.contains("\"speed_mps\":null")); assertTrue(text.contains("\"satellites_visible\":null"))
        assertTrue(text.contains("\"battery_percent\":null"))
        val battery = TelemetrySerializer.serialize(TelemetryMessage.fromNavigation(r.nav,
            TelemetryDiagnostics(health = SystemHealthSnapshot(batteryPercent = 82.0))), "s", 1)
        assertTrue(battery.contains("\"battery_percent\":82,"))
    }
    @Test fun nonfiniteLocalCoordinatesAreNullTogetherAndNeverNaN() {
        val r = Rig()
        val text = TelemetrySerializer.serialize(TelemetryMessage.fromNavigation(r.nav.copy(eastM = Double.NaN, speedMps = Double.POSITIVE_INFINITY), r.diagnostics), "s", 0)
        assertTrue(text.contains("\"local_east_m\":null")); assertTrue(text.contains("\"local_north_m\":null"))
        assertFalse(text.contains("NaN")); assertFalse(text.contains("Infinity"))
    }
    @Test fun historicalFixDoesNotClaimFreshRealMasking() {
        val r = Rig()
        val diagnostic = r.diagnostics.copy(gnss = GnssDiagnosticsSnapshot(blackoutMasksRealFix = true, blackoutMasksFreshFix = false))
        val text = TelemetrySerializer.serialize(TelemetryMessage.fromNavigation(r.nav, diagnostic), "s", 0)
        assertTrue(text.contains("\"blackout_masks_real_fix\":false"))
    }
    @Test fun latestSlotCoalescesAndSequenceIsAssignedOnSend() {
        val r = Rig(); r.start()
        repeat(1000) { r.publish(r.nav.copy(eastM = it.toDouble())) }
        assertEquals(1, r.client.status().queuedMessages)
        assertEquals(999L, r.client.status().coalescedMessages)
        r.client.pump()
        val messages = r.transport.sockets.last().messages
        assertEquals(1, messages.size); assertTrue(messages.single().contains("\"local_east_m\":999.0"))
        assertTrue(messages.single().contains("\"sequence\":0"))
        r.publish(); r.step()
        assertTrue(messages.last().contains("\"sequence\":1"))
    }
    @Test fun defaultFiveHertzRateIsBounded() {
        val r = Rig(); r.start()
        repeat(100) { r.publish(); r.client.pump(); r.now += 10_000_000 }
        assertEquals(5L, r.client.status().sentMessages)
    }
    @Test fun maximumTenHertzRateIsBounded() {
        val r = Rig(); r.start(500)
        repeat(100) { r.publish(); r.client.pump(); r.now += 10_000_000 }
        assertEquals(10L, r.client.status().sentMessages)
    }
    @Test fun disconnectDropsPendingAndDoesNotReconnectUntilRequested() {
        val r = Rig(); r.start(); r.publish(); r.client.disconnect(); r.client.pump(); r.step(30_000)
        assertTrue(r.transport.sockets.single().cancelled)
        assertEquals(0L, r.client.status().sentMessages)
        assertEquals(TelemetryConnectionState.DISCONNECTED, r.client.status().state)
        r.client.connect(); r.client.pump(); assertEquals(2, r.transport.sockets.size)
    }
    @Test fun retryIsExponentialBoundedAndFailureNeverEscapes() {
        val r = Rig(); r.start(); r.transport.sockets.last().failed(); r.client.pump()
        assertEquals(TelemetryConnectionState.RETRYING, r.client.status().state)
        r.step(999); assertEquals(1, r.transport.sockets.size)
        r.step(1); assertEquals(2, r.transport.sockets.size)
        assertEquals(listOf(1L, 2L, 4L, 8L, 16L, 30L, 30L), (1..7).map(TelemetryClient::retryDelaySeconds))
    }
    @Test fun connectingTimesOut() {
        val r = Rig()
        r.client.configure(TelemetryConfig(true, "ws://localhost/ws/telemetry"))
        r.token = r.client.startSession(); r.client.pump(); r.step(10_000)
        assertEquals(TelemetryConnectionState.RETRYING, r.client.status().state)
        assertTrue(r.transport.sockets.single().cancelled)
    }
    @Test fun socketBackpressureCancelsInsteadOfGrowingBuffer() {
        val r = Rig(); r.start(); r.transport.sockets.last().bytes = TelemetryClient.MAX_SOCKET_BYTES
        r.publish(); r.client.pump()
        assertEquals(1L, r.client.status().droppedMessages)
        assertTrue(r.transport.sockets.last().cancelled); assertTrue(r.transport.sockets.last().messages.isEmpty())
    }
    @Test fun sendFailureIsContained() {
        val r = Rig(); r.start(); r.transport.sockets.last().accepts = false; r.publish(); r.client.pump()
        assertEquals(TelemetryConnectionState.RETRYING, r.client.status().state)
        assertEquals(1L, r.client.status().errorCount)
    }
    @Test fun socketCreationExceptionIsContained() {
        val r = Rig(); r.transport.throwOnOpen = true
        r.client.configure(TelemetryConfig(true, "ws://localhost/ws/telemetry")); r.token = r.client.startSession()
        r.client.pump()
        assertEquals(TelemetryConnectionState.RETRYING, r.client.status().state)
    }
    @Test fun newSessionResetsCountersAndRejectsOldProducerToken() {
        val r = Rig(); r.start(); r.publish(); r.client.pump(); val old = r.token
        r.client.stopSession(); r.client.pump(); r.token = r.client.startSession(); r.client.pump()
        r.transport.sockets.last().opened(); r.client.pump()
        assertNotEquals(old, r.token)
        r.client.publish(r.nav, r.diagnostics, old); r.client.pump()
        assertEquals(0L, r.client.status().sentMessages)
        r.publish(); r.client.pump()
        assertTrue(r.transport.sockets.last().messages.single().contains("\"sequence\":0"))
    }
    @Test fun lateCancelledSocketCannotReplaceNewConnectionOpenEvent() {
        val r = Rig(); r.start(); val old = r.transport.sockets.last()
        r.client.disconnect(); r.client.pump(); r.client.connect(); r.client.pump()
        r.transport.sockets.last().opened(); old.failed(); r.client.pump()
        assertEquals(TelemetryConnectionState.CONNECTED, r.client.status().state)
    }
    @Test fun disconnectDuringQueueInspectionDoesNotSend() {
        val r = Rig(); r.start()
        r.transport.sockets.last().onQueue = { r.client.disconnect() }
        r.publish(); r.client.pump()
        assertTrue(r.transport.sockets.last().messages.isEmpty())
    }
    @Test fun newSessionDuringQueueInspectionDoesNotSendOldMessage() {
        val r = Rig(); r.start()
        r.transport.sockets.last().onQueue = { r.client.startSession() }
        r.publish(); r.client.pump()
        assertTrue(r.transport.sockets.last().messages.isEmpty())
    }
    @Test fun shutdownClosesResourcesAndRejectsFurtherWork() {
        val r = Rig(); r.start(); r.client.shutdown(); r.client.pump(); r.publish()
        assertTrue(r.transport.shut); assertTrue(r.transport.sockets.last().cancelled)
        assertEquals(TelemetryConnectionState.SHUTDOWN, r.client.status().state)
        assertEquals(0, r.client.status().queuedMessages)
    }
}
