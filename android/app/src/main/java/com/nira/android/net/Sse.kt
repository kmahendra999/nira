package com.nira.android.net

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/** What one Server-Sent Events line turned out to be. */
sealed interface SseChunk {
    /** Text to append to the answer so far. */
    data class Text(val value: String) : SseChunk

    /** The server said `[DONE]`; stop reading. */
    data object Done : SseChunk
}

private val LENIENT = Json {
    ignoreUnknownKeys = true
    isLenient = true
}

/**
 * Pull the text out of one Server-Sent Events line.
 *
 * Returns null for everything that carries no content: blank keep-alive lines,
 * comments, the `role` frame the server opens with, and any delta without
 * text. Null has to mean "nothing to show here" rather than "the stream ended"
 * — a stream that stopped at the first empty frame would truncate most
 * answers at their first token, which is why [SseChunk.Done] is separate.
 */
fun parseSseChunk(line: String): SseChunk? {
    if (!line.startsWith("data:")) return null
    val payload = line.removePrefix("data:").trim()
    if (payload.isEmpty()) return null
    if (payload == "[DONE]") return SseChunk.Done

    val root = runCatching { LENIENT.parseToJsonElement(payload).jsonObject }.getOrNull()
        ?: return null

    // An error frame arrives in-band, mid-stream, long after a 200 went out.
    // Throwing here is the only way the phone can tell a failed answer from a
    // short one — otherwise the reply simply stops and looks finished.
    root["error"]?.let { error ->
        val message = runCatching {
            error.jsonObject["message"]?.jsonPrimitive?.content
        }.getOrNull() ?: error.toString()
        throw NiraException(message ?: "The desktop reported an error")
    }

    val delta = runCatching {
        root["choices"]?.jsonArray?.firstOrNull()?.jsonObject?.get("delta")?.jsonObject
    }.getOrNull() ?: return null

    val content = runCatching { delta["content"]?.jsonPrimitive?.content }.getOrNull()
    return content?.takeIf { it.isNotEmpty() }?.let(SseChunk::Text)
}
