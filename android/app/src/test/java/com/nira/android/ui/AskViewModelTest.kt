package com.nira.android.ui

import app.cash.turbine.test
import com.google.common.truth.Truth.assertThat
import com.nira.android.data.Desktop
import com.nira.android.data.DesktopRegistry
import com.nira.android.data.InMemorySecretStore
import com.nira.android.data.Microphone
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import kotlinx.coroutines.withTimeout
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.After
import org.junit.Before
import org.junit.Test

/**
 * The phone's half of "talk to your desktop": a prompt goes out, an answer
 * streams back, and voice reaches the user's own machine rather than a cloud
 * recogniser.
 *
 * Driven against a real HTTP server so the wire format is exercised, not a
 * mock's idea of it.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class AskViewModelTest {
    private lateinit var server: MockWebServer
    private lateinit var registry: DesktopRegistry

    /** Never records; the view model should report that rather than send silence. */
    private class SilentMic(private val wav: ByteArray? = null) : Microphone {
        override val level: Float = 0f
        var stopped = false
        override fun record(): ByteArray? = wav
        override fun stop() {
            stopped = true
        }
    }

    private lateinit var routes: Routes

    /**
     * Answers by path, not in enqueue order.
     *
     * The speech probe and the prompt are independent requests that race. With
     * a queue, whichever arrived first took the other's response — so a prompt
     * could be answered with a speech-health body, producing an empty reply
     * that looked exactly like a real one. Which test failed depended on
     * timing.
     */
    private class Routes : Dispatcher() {
        val chat = ArrayDeque<MockResponse>()
        var speech: MockResponse = notConfigured()
        var transcript: MockResponse? = null
        var projects: MockResponse = json("""{"projects":[]}""")
        var startedRun: MockResponse? = null
        val runStatus = ArrayDeque<MockResponse>()

        override fun dispatch(request: RecordedRequest): MockResponse {
            val path = request.path.orEmpty()
            return when {
                path.startsWith("/v1/projects/runs/") ->
                    runStatus.removeFirstOrNull() ?: MockResponse().setResponseCode(404)
                path.endsWith("/run") ->
                    startedRun ?: MockResponse().setResponseCode(501)
                path.startsWith("/v1/projects") -> projects
                path.startsWith("/v1/speech/health") -> speech
                path.startsWith("/v1/speech/transcribe") ->
                    transcript ?: MockResponse().setResponseCode(501)
                path.startsWith("/v1/chat/completions") ->
                    chat.removeFirstOrNull() ?: MockResponse().setResponseCode(500)
                else -> MockResponse().setResponseCode(404)
            }
        }

        companion object {
            fun json(body: String) = MockResponse()
                .setHeader("Content-Type", "application/json")
                .setBody(body)

            fun notConfigured() =
                json("""{"available":false,"reason":"No speech backend configured"}""")
        }
    }

    @Before
    fun setUp() {
        // A real dispatcher for the same reason: virtual time and a real
        // HTTP server do not share a clock.
        Dispatchers.setMain(Dispatchers.Unconfined)
        routes = Routes()
        server = MockWebServer().apply {
            dispatcher = routes
            start()
        }
        registry = DesktopRegistry(InMemorySecretStore())
    }

    @After
    fun tearDown() {
        server.shutdown()
        Dispatchers.resetMain()
    }

    /** Scopes exclude "watch" by default so no event socket is opened. */
    private fun pair(scopes: List<String> = listOf("ask")) {
        registry.save(
            Desktop(
                id = "dev_1",
                name = "laptop",
                baseUrl = server.url("/").toString().trimEnd('/'),
                deviceKey = "nira_dk_secret",
                scopes = scopes,
            )
        )
    }

    private fun sse(vararg tokens: String): MockResponse {
        val body = buildString {
            append("data: {\"choices\":[{\"delta\":{\"role\":\"assistant\"}}]}\n\n")
            tokens.forEach {
                append("data: {\"choices\":[{\"delta\":{\"content\":\"$it\"}}]}\n\n")
            }
            append("data: [DONE]\n\n")
        }
        return MockResponse()
            .setHeader("Content-Type", "text/event-stream")
            .setBody(body)
    }

    private fun speechAvailable() = MockResponse()
        .setHeader("Content-Type", "application/json")
        .setBody("""{"available":true,"backend":"whisper"}""")

    /** Pull requests until one hits [path]; probes race the thing under test. */
    private fun requestFor(path: String): RecordedRequest {
        repeat(6) {
            val request = server.takeRequest()
            if (request.path?.startsWith(path) == true) return request
        }
        throw AssertionError("no request to $path")
    }

    @Test
    fun `a prompt streams back token by token`() = runBlocking {
        routes.chat += sse("Hel", "lo", " there")
        pair()

        val model = AskViewModel(registry, SilentMic())
        model.state.test {
            skipCurrent()
            model.send("hi")
            val settled = awaitSettled()
            assertThat(settled.turns.map { it.role }).containsExactly("user", "assistant")
            assertThat(settled.turns.last().text).isEqualTo("Hello there")
            assertThat(settled.turns.last().streaming).isFalse()
            assertThat(settled.error).isNull()
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `the prompt reaches the completions endpoint with the device key`() = runBlocking {
        routes.chat += sse("ok")
        pair()

        val model = AskViewModel(registry, SilentMic())
        model.state.test {
            skipCurrent()
            model.send("what is the time")
            awaitSettled()
            cancelAndIgnoreRemainingEvents()
        }

        val request = requestFor("/v1/chat/completions")
        assertThat(request.getHeader("Authorization")).isEqualTo("Bearer nira_dk_secret")
        val body = request.body.readUtf8()
        assertThat(body).contains("what is the time")
        assertThat(body).contains("\"stream\":true")
    }

    @Test
    fun `earlier turns are sent as history`() = runBlocking {
        routes.chat += sse("Paris")
        routes.chat += sse("About two million")
        pair()

        val model = AskViewModel(registry, SilentMic())
        model.state.test {
            skipCurrent()
            model.send("capital of France?")
            awaitSettled()
            model.send("how many people live there?")
            awaitSettled()
            cancelAndIgnoreRemainingEvents()
        }

        requestFor("/v1/chat/completions")
        val second = requestFor("/v1/chat/completions").body.readUtf8()
        // Without history the desktop cannot know what "there" refers to.
        assertThat(second).contains("capital of France?")
        assertThat(second).contains("Paris")
        assertThat(second).contains("how many people live there?")
    }

    @Test
    fun `a refused request surfaces the reason and drops the empty bubble`() = runBlocking {
        routes.chat += MockResponse().setResponseCode(401).setBody("nope")
        pair()

        val model = AskViewModel(registry, SilentMic())
        model.state.test {
            skipCurrent()
            model.send("hi")
            val failed = awaitUntil(timeoutMs = 5_000) { it.error != null }
            assertThat(failed.error).contains("not paired")
            // The placeholder bubble must go; an empty assistant turn left on
            // screen reads as an answer of nothing rather than a failure.
            assertThat(failed.turns.none { it.streaming }).isTrue()
            assertThat(failed.sending).isFalse()
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `an in-band error mid-stream is reported rather than truncating`() = runBlocking {
        routes.chat += MockResponse()
            .setHeader("Content-Type", "text/event-stream")
            .setBody(
                "data: {\"choices\":[{\"delta\":{\"content\":\"Thin\"}}]}\n\n" +
                    "data: {\"error\":{\"message\":\"context window exceeded\"}}\n\n"
            )
        pair()

        val model = AskViewModel(registry, SilentMic())
        model.state.test {
            skipCurrent()
            model.send("hi")
            val failed = awaitUntil(timeoutMs = 5_000) { it.error != null }
            assertThat(failed.error).contains("context window exceeded")
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `sending with no desktop paired says so`() = runBlocking {
        val model = AskViewModel(registry, SilentMic())
        model.send("hi")
        assertThat(model.state.value.error).isEqualTo("Pair a desktop first")
    }

    @Test
    fun `blank prompts are ignored`() = runBlocking {
        pair()
        val model = AskViewModel(registry, SilentMic())
        model.send("   ")
        assertThat(model.state.value.turns).isEmpty()
        assertThat(model.state.value.sending).isFalse()
    }

    @Test
    fun `the microphone is offered only when the desktop can transcribe`() = runBlocking {
        routes.speech = speechAvailable()
        pair()

        val model = AskViewModel(registry, SilentMic())
        model.state.test {
            val ready = awaitUntil(timeoutMs = 5_000) { it.canTranscribe != null }
            assertThat(ready.canTranscribe).isTrue()
            assertThat(ready.micUnavailableReason).isNull()
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `a desktop without speech explains why the microphone is missing`() = runBlocking {
        pair()

        val model = AskViewModel(registry, SilentMic())
        model.state.test {
            val ready = awaitUntil(timeoutMs = 5_000) { it.canTranscribe != null }
            assertThat(ready.canTranscribe).isFalse()
            assertThat(ready.micUnavailableReason).contains("No speech backend")
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `speech is transcribed on the desktop and sent as a prompt`() = runBlocking {
        routes.speech = speechAvailable()
        routes.transcript = MockResponse()
            .setHeader("Content-Type", "application/json")
            .setBody("""{"text":"turn on the lights","language":"en"}""")
        routes.chat += sse("Done")
        pair()

        val model = AskViewModel(registry, SilentMic(wav = ByteArray(64) { 1 }))
        model.state.test {
            skipCurrent()
            model.startRecording()
            val settled = awaitSettled(timeoutMs = 10_000)
            assertThat(settled.turns.first().text).isEqualTo("turn on the lights")
            assertThat(settled.turns.last().text).isEqualTo("Done")
            assertThat(settled.mic).isEqualTo(MicState.Idle)
            cancelAndIgnoreRemainingEvents()
        }

        val upload = requestFor("/v1/speech/transcribe")
        // The audio must reach the user's own machine, not a cloud recogniser.
        assertThat(upload.getHeader("Content-Type")).contains("multipart/form-data")
        assertThat(upload.body.readUtf8()).contains("speech.wav")
    }

    @Test
    fun `a take too short to be speech is reported rather than sent`() = runBlocking {
        routes.speech = speechAvailable()
        pair()

        val mic = SilentMic(wav = null)
        val model = AskViewModel(registry, mic)
        model.state.test {
            skipCurrent()
            model.startRecording()
            val failed = awaitUntil(timeoutMs = 5_000) { it.error != null }
            assertThat(failed.error).contains("Nothing was recorded")
            assertThat(failed.mic).isEqualTo(MicState.Idle)
            assertThat(failed.turns).isEmpty()
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `an empty transcript is reported rather than sent as a blank prompt`() = runBlocking {
        routes.speech = speechAvailable()
        routes.transcript = MockResponse()
            .setHeader("Content-Type", "application/json")
            .setBody("""{"text":"   "}""")
        pair()

        val model = AskViewModel(registry, SilentMic(wav = ByteArray(64)))
        model.state.test {
            skipCurrent()
            model.startRecording()
            val failed = awaitUntil(timeoutMs = 5_000) { it.error != null }
            assertThat(failed.error).contains("Could not make that out")
            assertThat(failed.turns).isEmpty()
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `releasing the button stops the recording`() = runBlocking {
        routes.speech = speechAvailable()
        pair()
        val mic = SilentMic(wav = ByteArray(64))
        val model = AskViewModel(registry, mic)
        model.stopRecording()
        assertThat(mic.stopped).isTrue()
    }

    @Test
    fun `a desktop without the watch scope opens no event socket`() = runBlocking {
        pair(scopes = listOf("ask"))

        val model = AskViewModel(registry, SilentMic())
        model.state.test {
            awaitUntil(timeoutMs = 5_000) { it.canTranscribe != null }
            cancelAndIgnoreRemainingEvents()
        }

        // Only the speech probe. A phone that was never granted "watch" must
        // not try to read the desktop's activity anyway.
        val paths = generateSequence { server.takeRequest(100, java.util.concurrent.TimeUnit.MILLISECONDS) }
            .map { it.path.orEmpty() }
            .toList()
        assertThat(paths.none { it.startsWith("/v1/agents/events") }).isTrue()
    }

    @Test
    fun `switching desktops clears the previous conversation`() = runBlocking {
        routes.chat += sse("first answer")
        pair()

        val model = AskViewModel(registry, SilentMic())
        model.state.test {
            skipCurrent()
            model.send("hi")
            assertThat(awaitSettled().turns).hasSize(2)

            registry.save(
                Desktop(
                    id = "dev_2",
                    name = "desktop",
                    baseUrl = server.url("/").toString().trimEnd('/'),
                    deviceKey = "nira_dk_other",
                    scopes = listOf("ask"),
                )
            )
            registry.select("dev_2")
            model.reload()

            // That conversation belongs to the other machine — the answers
            // came from its model, its files and its tools.
            assertThat(model.state.value.turns).isEmpty()
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `stopping keeps what arrived and stops asking for more`() = runBlocking {
        // A body with no terminator: the server would keep the connection open,
        // so only the stop can end this.
        routes.chat += MockResponse()
            .setHeader("Content-Type", "text/event-stream")
            .setBody("data: {\"choices\":[{\"delta\":{\"content\":\"Half an ans\"}}]}\n\n")
        pair()

        val model = AskViewModel(registry, SilentMic())
        model.state.test {
            skipCurrent()
            model.send("go on then")
            awaitUntil(timeoutMs = 5_000) { it.turns.lastOrNull()?.text == "Half an ans" }

            model.stopStreaming()

            val stopped = awaitUntil(timeoutMs = 5_000) { !it.sending }
            // Partial text is still the answer the user got; throwing it away
            // would make "stop" indistinguishable from "undo".
            assertThat(stopped.turns.last().text).isEqualTo("Half an ans")
            assertThat(stopped.turns.none { it.streaming }).isTrue()
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `a desktop with no projects offers none`() = runBlocking {
        pair()
        val model = AskViewModel(registry, SilentMic())
        model.state.test {
            awaitUntil(timeoutMs = 5_000) { it.canTranscribe != null }
            // Not an error state: plenty of desktops have never had
            // `nira project add` run on them.
            assertThat(model.state.value.projects).isEmpty()
            assertThat(model.state.value.error).isNull()
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `projects are offered when the desktop has them`() = runBlocking {
        routes.projects = Routes.json(
            """{"projects":[{"id":"p1","name":"nira","path":"/home/u/nira"}]}"""
        )
        pair()

        val model = AskViewModel(registry, SilentMic())
        model.state.test {
            val ready = awaitUntil(timeoutMs = 5_000) { it.projects.isNotEmpty() }
            assertThat(ready.projects.single().name).isEqualTo("nira")
            // Chat until the user says otherwise: pointing an agent at a
            // directory with file and shell access is not a default.
            assertThat(ready.project).isNull()
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `choosing a project sends the prompt there instead of to chat`() = runBlocking {
        routes.projects = Routes.json(
            """{"projects":[{"id":"p1","name":"nira","path":"/home/u/nira"}]}"""
        )
        routes.startedRun = Routes.json(
            """{"run":{"id":"run_1","project_id":"p1","project_name":"nira",""" +
                """"status":"running"}}"""
        )
        routes.runStatus += Routes.json(
            """{"id":"run_1","project_name":"nira","status":"done",""" +
                """"result":"Added the test.","turns":4}"""
        )
        pair()

        val model = AskViewModel(registry, SilentMic())
        model.state.test {
            val ready = awaitUntil(timeoutMs = 5_000) { it.projects.isNotEmpty() }
            model.chooseProject(ready.projects.single())
            model.send("add a test for the parser")

            val finished = awaitUntil(timeoutMs = 20_000) {
                it.run?.finished == true && it.turns.size >= 3
            }
            assertThat(finished.turns.first().text).isEqualTo("add a test for the parser")
            assertThat(finished.turns.last().text).isEqualTo("Added the test.")
            cancelAndIgnoreRemainingEvents()
        }

        val started = requestFor("/v1/projects/p1/run")
        assertThat(started.body.readUtf8()).contains("add a test for the parser")
    }

    @Test
    fun `a project run that will not start says why`() = runBlocking {
        routes.projects = Routes.json(
            """{"projects":[{"id":"p1","name":"nira","path":"/home/u/nira"}]}"""
        )
        routes.startedRun = MockResponse().setResponseCode(409)
            .setBody("""{"detail":"nira points at /gone, which is not a directory."}""")
        pair()

        val model = AskViewModel(registry, SilentMic())
        model.state.test {
            val ready = awaitUntil(timeoutMs = 5_000) { it.projects.isNotEmpty() }
            model.chooseProject(ready.projects.single())
            model.send("work on it")

            val failed = awaitUntil(timeoutMs = 10_000) { it.error != null }
            assertThat(failed.error).contains("not a directory")
            assertThat(failed.turns.none { it.streaming }).isTrue()
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `going back to chat stops using the project`() = runBlocking {
        routes.projects = Routes.json(
            """{"projects":[{"id":"p1","name":"nira","path":"/home/u/nira"}]}"""
        )
        routes.chat += sse("plain answer")
        pair()

        val model = AskViewModel(registry, SilentMic())
        model.state.test {
            val ready = awaitUntil(timeoutMs = 5_000) { it.projects.isNotEmpty() }
            model.chooseProject(ready.projects.single())
            model.chooseProject(null)
            model.send("just answer me")

            val settled = awaitSettled(timeoutMs = 10_000)
            assertThat(settled.turns.last().text).isEqualTo("plain answer")
            cancelAndIgnoreRemainingEvents()
        }

        assertThat(requestFor("/v1/chat/completions")).isNotNull()
    }

    // --- helpers -----------------------------------------------------------

    private suspend fun app.cash.turbine.TurbineTestContext<AskState>.skipCurrent() {
        awaitItem()
    }

    private suspend fun app.cash.turbine.TurbineTestContext<AskState>.awaitUntil(
        timeoutMs: Long = 5_000,
        predicate: (AskState) -> Boolean,
    ): AskState = withTimeout(timeoutMs) {
        while (true) {
            val state = awaitItem()
            if (predicate(state)) return@withTimeout state
        }
        @Suppress("UNREACHABLE_CODE")
        error("unreachable")
    }

    /** Wait for a completed answer: not sending, with a settled assistant turn. */
    private suspend fun app.cash.turbine.TurbineTestContext<AskState>.awaitSettled(
        timeoutMs: Long = 5_000,
    ): AskState = awaitUntil(timeoutMs) { state ->
        !state.sending && state.turns.isNotEmpty() && state.turns.none { it.streaming }
    }
}
