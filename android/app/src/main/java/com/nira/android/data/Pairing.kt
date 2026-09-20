package com.nira.android.data

import kotlinx.serialization.json.Json

/**
 * Reads what `nira device pair` put in the QR.
 *
 * Also accepts a bare token, because a QR is not always scannable — a headless
 * desktop over SSH, a cracked camera, a screen the user cannot point a phone
 * at — and in that case the user types the token and the host separately.
 */
object Pairing {
    private val json = Json { ignoreUnknownKeys = true; isLenient = true }

    private const val TOKEN_PREFIX = "nira_en_"

    sealed interface Result {
        data class Complete(val url: String, val token: String, val name: String) : Result
        /** A token with no address: the user still has to say which desktop. */
        data class TokenOnly(val token: String) : Result
        data class Invalid(val reason: String) : Result
    }

    fun parse(scanned: String): Result {
        val text = scanned.trim()
        if (text.isEmpty()) return Result.Invalid("Nothing scanned")

        if (text.startsWith("{")) {
            val payload = runCatching {
                json.decodeFromString(PairingPayload.serializer(), text)
            }.getOrNull() ?: return Result.Invalid("Could not read that code")

            if (!looksLikeToken(payload.token)) {
                return Result.Invalid("That code has no pairing token")
            }
            val url = normaliseUrl(payload.url)
                ?: return Result.Invalid("That code has no usable address")
            return Result.Complete(url, payload.token, payload.name)
        }

        if (looksLikeToken(text)) return Result.TokenOnly(text)

        return Result.Invalid("That does not look like a Nira pairing code")
    }

    fun looksLikeToken(value: String): Boolean =
        value.startsWith(TOKEN_PREFIX) && value.length > TOKEN_PREFIX.length

    /**
     * Accept what a person would type and make it a usable origin.
     *
     * A bare host is assumed https: the desktop needs TLS for the web app to
     * install anyway, and defaulting the other way would silently downgrade
     * a connection carrying a device key.
     */
    fun normaliseUrl(raw: String): String? {
        val text = raw.trim().trimEnd('/')
        if (text.isEmpty()) return null
        val withScheme = when {
            text.startsWith("http://") || text.startsWith("https://") -> text
            else -> "https://$text"
        }
        // Reject anything with whitespace or no host.
        val host = withScheme.substringAfter("://").substringBefore('/')
        if (host.isEmpty() || host.any { it.isWhitespace() }) return null
        return withScheme
    }
}
