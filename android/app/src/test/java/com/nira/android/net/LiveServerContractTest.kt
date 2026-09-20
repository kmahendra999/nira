package com.nira.android.net

import com.google.common.truth.Truth.assertThat
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.runBlocking
import org.junit.Assume.assumeTrue
import org.junit.Test

/**
 * Runs this client against a real `nira serve`, not a mock.
 *
 * MockWebServer proves the client does what the tests say. It cannot prove the
 * tests describe the server — that is exactly the gap where a client and its
 * backend drift apart. Set NIRA_TEST_URL (and NIRA_TEST_ENROLL_TOKEN for the
 * pairing leg) to check against the real thing; skipped otherwise, so an
 * ordinary build does not need a server running.
 */
class LiveServerContractTest {
    private val baseUrl: String? = System.getenv("NIRA_TEST_URL")
    private val enrollToken: String? = System.getenv("NIRA_TEST_ENROLL_TOKEN")
    private val deviceKey: String? = System.getenv("NIRA_TEST_DEVICE_KEY")

    @Test
    fun `enrolment against a real server yields a usable key`() = runBlocking {
        assumeTrue("NIRA_TEST_URL not set", baseUrl != null)
        assumeTrue("NIRA_TEST_ENROLL_TOKEN not set", enrollToken != null)

        val enrolled = NiraClient(baseUrl!!).enroll(enrollToken!!, platform = "android")

        assertThat(enrolled.key).startsWith("nira_dk_")
        assertThat(enrolled.scopes).isNotEmpty()

        // The key the server just issued must actually authenticate.
        val info = NiraClient(baseUrl, enrolled.key).info()
        assertThat(info).isNotNull()
    }

    @Test
    fun `a device key authenticates against a real server`() = runBlocking {
        assumeTrue("NIRA_TEST_URL not set", baseUrl != null)
        assumeTrue("NIRA_TEST_DEVICE_KEY not set", deviceKey != null)

        val info = NiraClient(baseUrl!!, deviceKey!!).info()

        assertThat(info).isNotNull()
    }

    @Test
    fun `no key is refused by a real server`() = runBlocking {
        assumeTrue("NIRA_TEST_URL not set", baseUrl != null)

        val error = runCatching { NiraClient(baseUrl!!).info() }.exceptionOrNull()

        assertThat(error).isInstanceOf(NiraException::class.java)
        assertThat((error as NiraException).code).isEqualTo(401)
    }

    @Test
    fun `a real server streams an answer back`() = runBlocking {
        assumeTrue("NIRA_TEST_URL not set", baseUrl != null)
        assumeTrue("NIRA_TEST_DEVICE_KEY not set", deviceKey != null)

        val tokens = NiraClient(baseUrl!!, deviceKey!!)
            .ask("Reply with the single word: pong")
            .toList()

        // The shape is what matters here, not the wording: the stream has to
        // arrive in pieces and add up to something.
        assertThat(tokens).isNotEmpty()
        assertThat(tokens.joinToString("")).isNotEmpty()
    }

    @Test
    fun `a real server reports whether it can transcribe`() = runBlocking {
        assumeTrue("NIRA_TEST_URL not set", baseUrl != null)
        assumeTrue("NIRA_TEST_DEVICE_KEY not set", deviceKey != null)

        val health = NiraClient(baseUrl!!, deviceKey!!).speechHealth()

        // Either answer is valid — a desktop without Whisper is a normal
        // configuration. What must hold is that the phone can find out, since
        // it decides whether to offer the microphone at all.
        if (!health.available) {
            assertThat(health.reason).isNotNull()
        }
    }
}
