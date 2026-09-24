package com.nira.android.net

import com.nira.android.data.AppVersion
import com.nira.android.data.Release
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

/**
 * The newest published release, from GitHub.
 *
 * `/releases/latest` deliberately, not `/releases`: it excludes prereleases,
 * and the desktop bundles are published continuously to a rolling prerelease
 * tag. Listing all of them would offer a phone an update named after a
 * desktop edge build.
 */
class UpdateClient(
    private val client: OkHttpClient = defaultClient(),
    private val latestUrl: String = LATEST_URL,
) {
    /** The latest release, or null when it cannot be read. */
    suspend fun latest(): Release? = withContext(Dispatchers.IO) {
        runCatching { fetch() }.getOrNull()
    }

    private fun fetch(): Release? {
        val request = Request.Builder()
            .url(latestUrl)
            .header("Accept", "application/vnd.github+json")
            .build()
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) return null
            val body = response.body?.string().orEmpty()
            if (body.isEmpty()) return null
            return parse(body)
        }
    }

    internal fun parse(body: String): Release? {
        val root = runCatching { JSON.parseToJsonElement(body).jsonObject }.getOrNull()
            ?: return null
        val tag = root["tag_name"]?.jsonPrimitive?.contentOrNullSafe().orEmpty()
        val version = AppVersion.parse(tag) ?: return null
        // The asset the release script uploads. A release with no apk is a
        // desktop-only one and is not an update this app can offer.
        val apkUrl = root["assets"]?.jsonArray
            ?.mapNotNull { it.jsonObject }
            ?.firstOrNull {
                it["name"]?.jsonPrimitive?.contentOrNullSafe()?.endsWith(".apk") == true
            }
            ?.get("browser_download_url")?.jsonPrimitive?.contentOrNullSafe()
            .orEmpty()
        if (apkUrl.isEmpty()) return null
        return Release(
            tag = tag,
            version = version,
            apkUrl = apkUrl,
            pageUrl = root["html_url"]?.jsonPrimitive?.contentOrNullSafe().orEmpty(),
            notes = root["body"]?.jsonPrimitive?.contentOrNullSafe().orEmpty(),
        )
    }

    companion object {
        const val LATEST_URL =
            "https://api.github.com/repos/kmahendra999/nira/releases/latest"

        private val JSON = Json { ignoreUnknownKeys = true }

        /**
         * Short timeouts. This runs at launch and nothing depends on its
         * answer, so it must never be the reason the app feels slow.
         */
        private fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(5, TimeUnit.SECONDS)
            .readTimeout(5, TimeUnit.SECONDS)
            .build()
    }
}

/** `content` throws on JSON null; this returns null instead. */
private fun kotlinx.serialization.json.JsonPrimitive.contentOrNullSafe(): String? =
    runCatching { if (this.toString() == "null") null else content }.getOrNull()
