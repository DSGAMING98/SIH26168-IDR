package org.sih26168.idrlogger.telemetry

import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.*
import org.junit.Test
import org.sih26168.idrlogger.engine.NavigationState

/** Actual loopback HTTP upgrade and WebSocket delivery, not a fake transport. */
class TelemetryWireTest {
    @Test fun okhttpDeliversVersionedSnapshotOverRealLoopbackSocket() {
        val server = MockWebServer()
        val received = AtomicReference<String?>()
        val opened = CountDownLatch(1); val delivered = CountDownLatch(1)
        server.enqueue(MockResponse().withWebSocketUpgrade(object : WebSocketListener() {
            override fun onMessage(webSocket: WebSocket, text: String) {
                received.set(text); delivered.countDown()
            }
        }))
        server.start()
        val transport = OkHttpTelemetryTransport()
        try {
            val socket = transport.open(server.url("/ws/telemetry").toString().replace("http://", "ws://"), { opened.countDown() }, {})
            assertTrue("WebSocket handshake", opened.await(5, TimeUnit.SECONDS))
            val json = TelemetrySerializer.serialize(TelemetryMessage.fromNavigation(NavigationState(), TelemetryDiagnostics()), "wire-test", 0)
            assertTrue(socket.send(json))
            assertTrue("WebSocket payload", delivered.await(5, TimeUnit.SECONDS))
            assertEquals(json, received.get())
            socket.cancel()
        } finally { transport.shutdown(); server.shutdown() }
    }
}
