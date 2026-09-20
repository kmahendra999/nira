package com.nira.android.net

import com.nira.android.data.AgentEvent
import com.nira.android.data.EnrollRequest
import com.nira.android.data.EnrollResponse
import com.nira.android.data.Project
import com.nira.android.data.ProjectList
import com.nira.android.data.ProjectRun
import com.nira.android.data.ProjectRunEnvelope
import com.nira.android.data.ServerInfo
import com.nira.android.data.Approval
import com.nira.android.data.ApprovalQueue
import com.nira.android.data.ChatTurn
import com.nira.android.data.SpeechHealth
import com.nira.android.data.Transcript
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.io.IOException
import java.util.Base64
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

private val JSON = "application/json; charset=utf-8".toMediaType()
private val WAV = "audio/wav".toMediaType()

/** Matches the server's WebSocket subprotocol auth (see auth_middleware.py). */
private const val WS_AUTH_PROTOCOL = "nira.auth.v1"
private const val WS_KEY_PROTOCOL_PREFIX = "nira.key.b64url."

class NiraException(message: String, val code: Int? = null) : Exception(message)

/**
 * HTTP and WebSocket client for one desktop.
 *
 * Auth is a bearer token in a header. That is simpler on Android than in the
 * browser, where the key has to be smuggled through a WebSocket subprotocol
 * because the WebSocket API cannot set headers — here the subprotocol dance is
 * only needed because the *server* expects it on the events socket.
 */
class NiraClient(
    baseUrl: String,
    private val deviceKey: String? = null,
    private val http: OkHttpClient = defaultClient(),
    private val json: Json = defaultJson(),
) {
    /** Normalised once: a trailing slash would produce `//v1/...` paths. */
    private val base: String = baseUrl.trimEnd('/')

    companion object {
        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            // Generous read timeout: a completion streams for as long as the
            // model takes, and a short one would sever it mid-reply.
            .readTimeout(5, TimeUnit.MINUTES)
            // Keep the events socket alive across a phone's idle radio.
            .pingInterval(20, TimeUnit.SECONDS)
            .build()

        fun defaultJson(): Json = Json {
            // Tolerate fields the server grows that this client does not know,
            // so an upgraded desktop does not break an older phone.
            ignoreUnknownKeys = true
            isLenient = true
            // Send fields that happen to equal their default. Without this a
            // defaulted `platform` is omitted entirely and every device
            // registers as "unknown" — the value is a default on *this* side,
            // not an instruction to leave it out of the request.
            encodeDefaults = true
        }

        /** Encode a key as a WebSocket subprotocol token, as the server expects. */
        fun keyProtocol(key: String): String {
            val encoded = Base64.getUrlEncoder().withoutPadding()
                .encodeToString(key.toByteArray(Charsets.UTF_8))
            return "$WS_KEY_PROTOCOL_PREFIX$encoded"
        }
    }

    private fun Request.Builder.withAuth(): Request.Builder =
        if (deviceKey.isNullOrEmpty()) this
        else header("Authorization", "Bearer $deviceKey")

    /**
     * Redeem a pairing invitation for this device's own key.
     *
     * Intentionally unauthenticated: a device that has not paired has nothing
     * to present, and the invitation is the credential.
     */
    suspend fun enroll(token: String, platform: String = "android"): EnrollResponse {
        val body = json.encodeToString(EnrollRequest.serializer(), EnrollRequest(token, platform))
        val request = Request.Builder()
            .url("$base/v1/devices/enroll")
            .post(body.toRequestBody(JSON))
            .build()
        return json.decodeFromString(EnrollResponse.serializer(), execute(request))
    }

    /** Identity and liveness. Used by the desktop picker to show what is up. */
    suspend fun info(): ServerInfo {
        val request = Request.Builder().url("$base/v1/info").withAuth().build()
        return json.decodeFromString(ServerInfo.serializer(), execute(request))
    }

    /**
     * Subscribe to agent progress, resuming from [since] after a drop.
     *
     * The cursor is the point. A phone loses this socket constantly — cell
     * handover, screen lock, walking out of range — and without resuming,
     * every reconnect silently loses whatever happened in the gap and progress
     * appears to stall.
     */
    fun agentEvents(agentId: String? = null, since: Long? = null): Flow<AgentEvent> =
        callbackFlow {
            val url = buildString {
                append(base.replaceFirst("http", "ws"))
                append("/v1/agents/events")
                val params = buildList {
                    agentId?.let { add("agent_id=$it") }
                    since?.let { add("since=$it") }
                }
                if (params.isNotEmpty()) append("?").append(params.joinToString("&"))
            }

            val builder = Request.Builder().url(url)
            if (!deviceKey.isNullOrEmpty()) {
                builder.header(
                    "Sec-WebSocket-Protocol",
                    "$WS_AUTH_PROTOCOL, ${keyProtocol(deviceKey)}",
                )
            }

            val socket = http.newWebSocket(
                builder.build(),
                object : WebSocketListener() {
                    override fun onMessage(webSocket: WebSocket, text: String) {
                        val event = runCatching {
                            json.decodeFromString(AgentEvent.serializer(), text)
                        }.getOrNull() ?: return
                        trySend(event)
                    }

                    override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                        close()
                    }

                    override fun onFailure(
                        webSocket: WebSocket,
                        t: Throwable,
                        response: Response?,
                    ) {
                        // Surface it rather than closing quietly: a caller that
                        // cannot tell "finished" from "connection died" cannot
                        // decide whether to reconnect.
                        close(NiraException(t.message ?: "socket failed", response?.code))
                    }
                },
            )

            awaitClose { socket.cancel() }
        }


    /**
     * Ask the desktop something, streaming the answer back a token at a time.
     *
     * Streaming rather than one blocking call because on a phone the wait is
     * the whole experience: a spinner for thirty seconds reads as a hang,
     * while text that starts arriving immediately reads as thinking.
     */
    fun ask(prompt: String, history: List<ChatTurn> = emptyList()): Flow<String> = flow {
        val payload = buildJsonObject {
            put("model", JsonPrimitive("default"))
            put("stream", JsonPrimitive(true))
            put(
                "messages",
                buildJsonArray {
                    (history + ChatTurn("user", prompt)).forEach { turn ->
                        add(
                            buildJsonObject {
                                put("role", JsonPrimitive(turn.role))
                                put("content", JsonPrimitive(turn.content))
                            }
                        )
                    }
                },
            )
        }
        val request = Request.Builder()
            .url("$base/v1/chat/completions")
            .post(payload.toString().toRequestBody(JSON))
            .header("Accept", "text/event-stream")
            .withAuth()
            .build()

        val call = http.newCall(request)
        // Cancelling the collector has to reach the socket. Without this the
        // read below stays parked until the server happens to send more, so
        // "stop" would leave a completion running and billing tokens.
        currentCoroutineContext()[Job]?.invokeOnCompletion { call.cancel() }

        val response = runCatching { call.execute() }
            .getOrElse { throw NiraException(it.message ?: "request failed") }
        response.use {
            val body = it.body ?: throw NiraException("empty response", it.code)
            if (!it.isSuccessful) {
                throw NiraException(describe(it.code, body.string()), it.code)
            }
            val source = body.source()
            while (true) {
                currentCoroutineContext().ensureActive()
                val line = source.readUtf8Line() ?: break
                when (val chunk = parseSseChunk(line)) {
                    null -> continue
                    SseChunk.Done -> break
                    is SseChunk.Text -> emit(chunk.value)
                }
            }
        }
    }
        // Blocking I/O belongs off whatever thread collects this. Leaving it
        // to callers means the one that forgets freezes the UI, and it will
        // look like the desktop is slow rather than like a bug here.
        .flowOn(Dispatchers.IO)

    /**
     * Transcribe recorded audio on the desktop.
     *
     * On the desktop, not on the phone. Android's own recogniser would ship
     * the user's voice to Google, which is the one thing a local-first
     * assistant exists to avoid — here the audio reaches only a machine the
     * user already owns.
     */
    suspend fun transcribe(wav: ByteArray, language: String? = null): Transcript {
        val form = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart("file", "speech.wav", wav.toRequestBody(WAV))
            .apply { language?.let { addFormDataPart("language", it) } }
            .build()
        val request = Request.Builder()
            .url("$base/v1/speech/transcribe")
            .post(form)
            .withAuth()
            .build()
        return json.decodeFromString(Transcript.serializer(), execute(request))
    }

    /** Whether this desktop can transcribe at all, and why not if it cannot. */
    suspend fun speechHealth(): SpeechHealth {
        val request = Request.Builder().url("$base/v1/speech/health").withAuth().build()
        return json.decodeFromString(SpeechHealth.serializer(), execute(request))
    }


    /**
     * The projects this desktop knows about.
     *
     * Empty is a normal answer, not a failure: a desktop where nobody has run
     * `nira project add` has none, and the phone should offer plain chat
     * rather than an empty picker.
     */
    suspend fun projects(): List<Project> {
        val request = Request.Builder().url("$base/v1/projects").withAuth().build()
        return json.decodeFromString(ProjectList.serializer(), execute(request)).projects
    }

    /**
     * Start agentic work in a project's directory.
     *
     * Returns as soon as the work is under way — the answer to "did it work?"
     * comes later, over the event socket and from [run]. A phone cannot hold
     * an HTTP request open for the minutes this takes.
     */
    suspend fun startRun(project: String, prompt: String): ProjectRun {
        val payload = buildJsonObject { put("prompt", JsonPrimitive(prompt)) }
        val request = Request.Builder()
            .url("$base/v1/projects/$project/run")
            .post(payload.toString().toRequestBody(JSON))
            .withAuth()
            .build()
        return json.decodeFromString(
            ProjectRunEnvelope.serializer(), execute(request)
        ).run
    }

    /** How a run turned out. */
    suspend fun run(runId: String): ProjectRun {
        val request = Request.Builder()
            .url("$base/v1/projects/runs/$runId")
            .withAuth()
            .build()
        return json.decodeFromString(ProjectRun.serializer(), execute(request))
    }


    /**
     * Steps waiting on a person.
     *
     * Needs the `approve` scope, which a device is granted only deliberately:
     * answering these is the most consequential thing a phone can do to a
     * desktop, since a yes lets an agent act with file and shell access.
     */
    suspend fun approvals(): List<Approval> {
        val request = Request.Builder()
            .url("$base/v1/approvals/pending")
            .withAuth()
            .build()
        return json.decodeFromString(ApprovalQueue.serializer(), execute(request)).actions
    }

    /** Allow a waiting step, or refuse it. The run resumes either way. */
    suspend fun decideApproval(id: String, approve: Boolean) {
        val verb = if (approve) "approve" else "deny"
        val request = Request.Builder()
            .url("$base/v1/approvals/$id/$verb")
            .post(ByteArray(0).toRequestBody(JSON))
            .withAuth()
            .build()
        execute(request)
    }

    private suspend fun execute(request: Request): String =
        suspendCancellableCoroutine { continuation ->
            val call = http.newCall(request)
            continuation.invokeOnCancellation { call.cancel() }
            call.enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) {
                    continuation.resumeWithException(
                        NiraException(e.message ?: "request failed")
                    )
                }

                override fun onResponse(call: Call, response: Response) {
                    response.use {
                        val body = it.body?.string().orEmpty()
                        if (!it.isSuccessful) {
                            continuation.resumeWithException(
                                NiraException(describe(it.code, body), it.code)
                            )
                        } else {
                            continuation.resume(body)
                        }
                    }
                }
            })
        }


    /**
     * Turn a failure into something a person can act on.
     *
     * The server's own `detail` wins whenever it sends one. A status code is
     * too blunt to explain itself: 403 means both "that pairing code expired"
     * and "this device was not granted admin access", and a fixed message for
     * the code would confidently give the wrong advice for the other case.
     */
    private fun describe(code: Int, body: String): String {
        detailFrom(body)?.let { return it }
        return when (code) {
            401 -> "This device is not paired with that desktop, or its access was revoked."
            403 -> "That desktop refused this request."
            429 -> "Too many requests. Wait a moment and try again."
            501 -> "That desktop does not have this feature enabled."
            else -> body.ifBlank { "Request failed ($code)" }
        }
    }

    /** Pull FastAPI's `detail` out of an error body, if it is one. */
    private fun detailFrom(body: String): String? = runCatching {
        json.parseToJsonElement(body).jsonObject["detail"]?.jsonPrimitive?.content
    }.getOrNull()?.takeIf { it.isNotBlank() }
}
