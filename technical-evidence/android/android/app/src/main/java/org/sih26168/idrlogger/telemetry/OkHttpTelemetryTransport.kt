package org.sih26168.idrlogger.telemetry

import java.util.concurrent.TimeUnit
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener

/** No incoming application message is consumed: a dashboard cannot control the vehicle. */
internal class OkHttpTelemetryTransport : TelemetryTransport {
    private val client = OkHttpClient.Builder().connectTimeout(8, TimeUnit.SECONDS)
        .writeTimeout(3, TimeUnit.SECONDS).readTimeout(0, TimeUnit.SECONDS)
        .pingInterval(15, TimeUnit.SECONDS).retryOnConnectionFailure(false).build()
    override fun open(endpoint: String, onOpen: () -> Unit, onFailure: () -> Unit): TelemetrySocket {
        val webSocket = client.newWebSocket(Request.Builder().url(endpoint).build(), object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) { onOpen() }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) { onFailure() }
            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) { webSocket.cancel(); onFailure() }
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { onFailure() }
        })
        return object : TelemetrySocket {
            override fun send(text: String) = webSocket.send(text)
            override fun queuedBytes() = webSocket.queueSize()
            override fun cancel() = webSocket.cancel()
        }
    }
    override fun shutdown() { client.dispatcher.executorService.shutdown(); client.connectionPool.evictAll() }
}
