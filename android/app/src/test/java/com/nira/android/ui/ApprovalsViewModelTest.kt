package com.nira.android.ui

import app.cash.turbine.test
import com.google.common.truth.Truth.assertThat
import com.nira.android.data.Desktop
import com.nira.android.data.DesktopRegistry
import com.nira.android.data.InMemorySecretStore
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
import java.util.concurrent.TimeUnit

/**
 * Answering a step an agent is parked on.
 *
 * This is the most consequential thing the phone can do to a desktop: a yes
 * lets an agent act with file and shell access. So the tests care as much
 * about what the phone refuses to do — answer without the scope, answer twice,
 * leave a settled question on screen — as about the happy path.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class ApprovalsViewModelTest {
    private lateinit var server: MockWebServer
    private lateinit var registry: DesktopRegistry
    private lateinit var routes: Routes

    private class Routes : Dispatcher() {
        var queue: MockResponse = json("""{"actions":[],"count":0}""")
        var decision: MockResponse = json("""{"status":"approved"}""")
        val decided = mutableListOf<String>()

        override fun dispatch(request: RecordedRequest): MockResponse {
            val path = request.path.orEmpty()
            return when {
                path.startsWith("/v1/approvals/pending") -> queue
                path.startsWith("/v1/approvals/") -> {
                    decided += path
                    decision
                }
                // The events socket: a plain 404 ends the flow, and the view
                // model's retry loop handles that without help.
                else -> MockResponse().setResponseCode(404)
            }
        }

        companion object {
            fun json(body: String) = MockResponse()
                .setHeader("Content-Type", "application/json")
                .setBody(body)
        }
    }

    @Before
    fun setUp() {
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

    private fun pair(scopes: List<String> = listOf("ask", "approve")) {
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

    private fun oneWaiting(tier: String = "high") = Routes.json(
        """{"actions":[{"id":"act_1","action_type":"tool:Bash",""" +
            """"description":"Claude wants to run rm -rf build",""" +
            """"payload":{"tool":"Bash","input":{"command":"rm -rf build"}},""" +
            """"permission_key":"tool:Bash:rm","tier":"$tier"}],"count":1}"""
    )

    @Test
    fun `a waiting step is listed with what it wants to do`() = runBlocking {
        routes.queue = oneWaiting()
        pair()

        val model = ApprovalsViewModel(registry)
        model.state.test {
            val ready = awaitUntil { it.waiting.isNotEmpty() }
            val approval = ready.waiting.single()
            assertThat(approval.description).contains("rm -rf build")
            // The exact command, not only the prose: approving a summary is
            // not approving what will actually run.
            assertThat(approval.detail).isEqualTo("rm -rf build")
            assertThat(approval.alwaysAsks).isTrue()
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `allowing sends an approve and clears the card`() = runBlocking {
        routes.queue = oneWaiting()
        pair()

        val model = ApprovalsViewModel(registry)
        model.state.test {
            awaitUntil { it.waiting.isNotEmpty() }
            model.decide("act_1", approve = true)
            val settled = awaitUntil { it.waiting.isEmpty() && it.deciding.isEmpty() }
            assertThat(settled.error).isNull()
            cancelAndIgnoreRemainingEvents()
        }

        assertThat(routes.decided).contains("/v1/approvals/act_1/approve")
    }

    @Test
    fun `refusing sends a deny`() = runBlocking {
        routes.queue = oneWaiting()
        pair()

        val model = ApprovalsViewModel(registry)
        model.state.test {
            awaitUntil { it.waiting.isNotEmpty() }
            model.decide("act_1", approve = false)
            awaitUntil { it.waiting.isEmpty() }
            cancelAndIgnoreRemainingEvents()
        }

        assertThat(routes.decided).contains("/v1/approvals/act_1/deny")
    }

    @Test
    fun `the card goes immediately rather than waiting for a refresh`() = runBlocking {
        // The run is parked on this answer. Leaving a settled question on
        // screen invites a second tap on something already decided.
        routes.queue = oneWaiting()
        pair()

        val model = ApprovalsViewModel(registry)
        model.state.test {
            awaitUntil { it.waiting.isNotEmpty() }
            model.decide("act_1", approve = true)
            assertThat(awaitUntil { it.waiting.isEmpty() }.waiting).isEmpty()
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `a second tap while the first is in flight is ignored`() = runBlocking {
        routes.queue = oneWaiting()
        // Hold the response open so both taps land while the first is pending.
        routes.decision = Routes.json("""{"status":"approved"}""")
            .setBodyDelay(300, TimeUnit.MILLISECONDS)
        pair()

        val model = ApprovalsViewModel(registry)
        model.state.test {
            awaitUntil { it.waiting.isNotEmpty() }
            model.decide("act_1", approve = true)
            model.decide("act_1", approve = true)
            awaitUntil(timeoutMs = 10_000) { it.deciding.isEmpty() && it.waiting.isEmpty() }
            cancelAndIgnoreRemainingEvents()
        }

        // Two approvals for one question is one more than there was a question.
        assertThat(routes.decided).hasSize(1)
    }

    @Test
    fun `a device without the approve scope is told so rather than shown nothing`() =
        runBlocking {
            routes.queue = oneWaiting()
            pair(scopes = listOf("ask", "watch"))

            val model = ApprovalsViewModel(registry)
            model.state.test {
                val ready = awaitUntil { it.desktop != null }
                // An empty list would read as "nothing is waiting", which is a
                // different and more dangerous thing to believe.
                assertThat(ready.canApprove).isFalse()
                assertThat(ready.waiting).isEmpty()
                cancelAndIgnoreRemainingEvents()
            }

            // It must not even ask: the server would refuse it anyway.
            val paths = generateSequence { server.takeRequest(100, TimeUnit.MILLISECONDS) }
                .map { it.path.orEmpty() }
                .toList()
            assertThat(paths.none { it.startsWith("/v1/approvals") }).isTrue()
        }

    @Test
    fun `a failing answer is reported and the card stays`() = runBlocking {
        routes.queue = oneWaiting()
        routes.decision = MockResponse().setResponseCode(404).setBody("""{"detail":"gone"}""")
        pair()

        val model = ApprovalsViewModel(registry)
        model.state.test {
            awaitUntil { it.waiting.isNotEmpty() }
            model.decide("act_1", approve = true)
            val failed = awaitUntil(timeoutMs = 10_000) { it.error != null }
            assertThat(failed.error).isNotEmpty()
            // Still there: the question was never answered, so pretending it
            // was would leave the run parked with nothing on screen about it.
            assertThat(failed.waiting).hasSize(1)
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `an unreachable desktop reports rather than looking empty`() = runBlocking {
        routes.queue = MockResponse().setResponseCode(500)
        pair()

        val model = ApprovalsViewModel(registry)
        model.state.test {
            val failed = awaitUntil(timeoutMs = 10_000) { it.error != null }
            assertThat(failed.loading).isFalse()
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `no desktop means nothing to answer`() = runBlocking {
        val model = ApprovalsViewModel(registry)
        assertThat(model.state.value.desktop).isNull()
        assertThat(model.state.value.waiting).isEmpty()
    }

    private suspend fun app.cash.turbine.TurbineTestContext<ApprovalsState>.awaitUntil(
        timeoutMs: Long = 5_000,
        predicate: (ApprovalsState) -> Boolean,
    ): ApprovalsState = withTimeout(timeoutMs) {
        while (true) {
            val state = awaitItem()
            if (predicate(state)) return@withTimeout state
        }
        @Suppress("UNREACHABLE_CODE")
        error("unreachable")
    }
}
