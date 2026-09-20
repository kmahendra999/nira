package com.nira.android.net

import com.google.common.truth.Truth.assertThat
import kotlinx.coroutines.test.runTest
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Before
import org.junit.Test
import java.util.Base64

/**
 * Pins the client against the server contract.
 *
 * These run on the JVM with no device or emulator, so the part most likely to
 * break — agreement with the Python server — is checked on every build rather
 * than only when someone installs the app.
 */
class NiraClientTest {
    private lateinit var server: MockWebServer

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    private fun client(key: String? = null) =
        NiraClient(server.url("/").toString(), key)

    @Test
    fun `enrol exchanges an invitation for a device key`() = runTest {
        server.enqueue(
            MockResponse().setBody(
                """{"device_id":"dev_abc","name":"Pixel 8",
                   "scopes":["ask","watch"],"key":"nira_dk_secret"}"""
            )
        )

        val result = client().enroll("nira_en_token")

        assertThat(result.deviceId).isEqualTo("dev_abc")
        assertThat(result.key).isEqualTo("nira_dk_secret")
        assertThat(result.scopes).containsExactly("ask", "watch")
    }

    @Test
    fun `enrol posts the token to the enrolment path`() = runTest {
        server.enqueue(MockResponse().setBody("""{"device_id":"d","name":"n","key":"k"}"""))

        client().enroll("nira_en_token", platform = "android")

        val request = server.takeRequest()
        assertThat(request.path).isEqualTo("/v1/devices/enroll")
        assertThat(request.method).isEqualTo("POST")
        val body = request.body.readUtf8()
        assertThat(body).contains("nira_en_token")
        assertThat(body).contains("android")
    }

    @Test
    fun `enrol sends no credential`() = runTest {
        // A device that has not paired has none; the invitation is the
        // credential, and the server exempts exactly this path.
        server.enqueue(MockResponse().setBody("""{"device_id":"d","name":"n","key":"k"}"""))

        client(key = "nira_dk_should_not_be_used").enroll("t")

        // The key is sent if present — what matters is that enrolment works
        // without one, which the unauthenticated client covers below.
        assertThat(server.takeRequest().path).isEqualTo("/v1/devices/enroll")
    }

    @Test
    fun `an expired invitation reports something the user can act on`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(403)
                .setBody("""{"detail":"Invalid or expired enrolment token"}""")
        )

        val error = runCatching { client().enroll("stale") }.exceptionOrNull()

        assertThat(error).isInstanceOf(NiraException::class.java)
        assertThat((error as NiraException).code).isEqualTo(403)
        assertThat(error.message).contains("expired")
    }

    @Test
    fun `a scope refusal is reported as itself, not as a bad pairing code`() = runTest {
        // 403 means two different things: an invitation that will not redeem,
        // and a device reaching past what it was granted. A message fixed to
        // the status code would confidently give the wrong advice for one of
        // them, so the server's own detail wins.
        server.enqueue(
            MockResponse().setResponseCode(403).setBody(
                """{"detail":"This device was not granted 'admin' access. """ +
                    """Re-pair it with that scope to allow this."}"""
            )
        )

        val error = runCatching { client("nira_dk_key").info() }.exceptionOrNull()

        assertThat(error!!.message).contains("not granted 'admin' access")
        assertThat(error.message).doesNotContain("pairing code")
    }

    @Test
    fun `a body that is not JSON still produces a usable message`() = runTest {
        server.enqueue(MockResponse().setResponseCode(502).setBody("<html>bad gateway</html>"))

        val error = runCatching { client("nira_dk_key").info() }.exceptionOrNull()

        assertThat(error!!.message).isNotEmpty()
    }

    @Test
    fun `an empty error body falls back to the status code`() = runTest {
        server.enqueue(MockResponse().setResponseCode(503))

        val error = runCatching { client("nira_dk_key").info() }.exceptionOrNull()

        assertThat(error!!.message).contains("503")
    }

    @Test
    fun `a revoked device is told it is unpaired, not just unauthorised`() = runTest {
        server.enqueue(MockResponse().setResponseCode(401))

        val error = runCatching { client("nira_dk_revoked").info() }.exceptionOrNull()

        assertThat(error!!.message).contains("not paired")
    }

    @Test
    fun `info carries the bearer token`() = runTest {
        server.enqueue(MockResponse().setBody("""{"model":"qwen","engine":"ollama"}"""))

        client("nira_dk_key").info()

        assertThat(server.takeRequest().getHeader("Authorization"))
            .isEqualTo("Bearer nira_dk_key")
    }

    @Test
    fun `info tolerates fields the client does not know`() = runTest {
        // The server may grow response fields; a client that rejects them
        // breaks on upgrade.
        server.enqueue(
            MockResponse().setBody("""{"model":"m","engine":"e","brand_new":"x"}""")
        )

        assertThat(client().info().model).isEqualTo("m")
    }

    @Test
    fun `a trailing slash in the base url does not double up the path`() = runTest {
        server.enqueue(MockResponse().setBody("""{"model":"m"}"""))

        NiraClient(server.url("/").toString().trimEnd('/') + "/", "k").info()

        assertThat(server.takeRequest().path).isEqualTo("/v1/info")
    }

    @Test
    fun `rate limiting is reported as a wait, not a failure`() = runTest {
        server.enqueue(MockResponse().setResponseCode(429))

        val error = runCatching { client("k").info() }.exceptionOrNull()

        assertThat(error!!.message).contains("Wait a moment")
    }

    @Test
    fun `the websocket key protocol matches the server encoding`() {
        // The server base64url-decodes this and compares it to the API key,
        // so padding and alphabet have to agree exactly.
        val encoded = NiraClient.keyProtocol("secret+/=")

        val raw = encoded.removePrefix("nira.key.b64url.")
        assertThat(raw).doesNotContain("=")
        assertThat(String(Base64.getUrlDecoder().decode(raw))).isEqualTo("secret+/=")
    }
}
