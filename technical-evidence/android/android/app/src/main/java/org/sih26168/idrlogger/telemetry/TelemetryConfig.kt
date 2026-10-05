package org.sih26168.idrlogger.telemetry

import android.content.Context
import java.net.URI

/** Opt-in observer settings. Cleartext also requires an explicitly trusted build-time LAN host. */
data class TelemetryConfig(val enabled: Boolean = false, val endpoint: String = "", val rateHz: Int = 5) {
    fun normalized() = copy(endpoint = endpoint.trim(), rateHz = rateHz.coerceIn(1, 10))

    fun validationError(): String? {
        if (!enabled && endpoint.isBlank()) return null
        val uri = try { URI(endpoint.trim()) } catch (_: Exception) { return "Enter a valid ws:// or wss:// endpoint" }
        if (uri.scheme !in setOf("ws", "wss") || uri.host.isNullOrBlank()) return "Use a ws:// or wss:// endpoint"
        if (uri.rawUserInfo != null || uri.rawQuery != null || uri.rawFragment != null) {
            return "Endpoint credentials, query strings and fragments are not supported"
        }
        if (uri.port != -1 && uri.port !in 1..65535) return "Endpoint port is invalid"
        if (uri.path != "/ws/telemetry") return "Endpoint path must be /ws/telemetry"
        if (uri.scheme == "ws" && !isPrivateHost(uri.host)) return "Use wss:// outside a trusted local network"
        return null
    }

    companion object {
        private fun isPrivateHost(host: String): Boolean {
            val h = host.lowercase().removePrefix("[").removeSuffix("]")
            if (h == "localhost" || h == "::1") return true
            if ((h.startsWith("fc") || h.startsWith("fd")) && ':' in h || h.startsWith("fe80:")) return true
            val parts = h.split('.').map { it.toIntOrNull() ?: return false }
            if (parts.size != 4 || parts.any { it !in 0..255 }) return false
            return parts[0] == 10 || parts[0] == 127 ||
                (parts[0] == 192 && parts[1] == 168) ||
                (parts[0] == 172 && parts[1] in 16..31) ||
                (parts[0] == 169 && parts[1] == 254)
        }
    }
}

class TelemetrySettings(context: Context) {
    private val preferences = context.getSharedPreferences("navghost_telemetry", Context.MODE_PRIVATE)
    fun load() = TelemetryConfig(
        preferences.getBoolean("enabled", false), preferences.getString("endpoint", "").orEmpty(),
        preferences.getInt("rate_hz", 5),
    ).normalized()

    fun save(config: TelemetryConfig): Boolean {
        val safe = config.normalized()
        if (safe.validationError() != null) return false
        preferences.edit().putBoolean("enabled", safe.enabled).putString("endpoint", safe.endpoint)
            .putInt("rate_hz", safe.rateHz).apply()
        return true
    }
}
