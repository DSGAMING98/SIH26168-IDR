package org.sih26168.idrlogger.telemetry

/** Strict JSON for the fixed field allowlist; cannot serialize an arbitrary model object. */
object TelemetrySerializer {
    fun serialize(message: TelemetryMessage, sessionId: String, sequence: Long): String {
        require(sessionId.matches(Regex("[A-Za-z0-9_-]{1,64}"))) { "Invalid session identifier" }
        require(sequence >= 0) { "Invalid sequence" }
        val fields = linkedMapOf<String, Any?>(
            "schema_version" to 1, "session_id" to sessionId, "sequence" to sequence,
            // Nanoseconds exceed JavaScript's exact integer range after a long device uptime.
            "timestamp_ns" to message.timestampNs.toString(),
        )
        fields.putAll(message.fields)
        return buildString(2048) { appendJson(fields) }
    }

    private fun StringBuilder.appendJson(value: Any?) {
        when (value) {
            null -> append("null")
            is String -> {
                append('"')
                value.forEach { c -> when (c) {
                    '"' -> append("\\\"")
                    '\\' -> append("\\\\")
                    '\n' -> append("\\n")
                    '\r' -> append("\\r")
                    '\t' -> append("\\t")
                    else -> if (c.code < 0x20) append("\\u%04x".format(c.code)) else append(c)
                } }
                append('"')
            }
            is Boolean, is Int, is Long -> append(value.toString())
            is Double -> if (value.isFinite()) append(value) else append("null")
            is Map<*, *> -> {
                append('{')
                value.entries.forEachIndexed { index, entry ->
                    if (index > 0) append(',')
                    require(entry.key is String)
                    appendJson(entry.key)
                    append(':')
                    appendJson(entry.value)
                }
                append('}')
            }
            else -> error("Unsupported telemetry value")
        }
    }
}
