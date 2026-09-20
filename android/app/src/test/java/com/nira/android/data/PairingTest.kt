package com.nira.android.data

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/** Reads what `nira device pair` encodes, and what a person types instead. */
class PairingTest {
    @Test
    fun `reads the QR payload the desktop emits`() {
        val scanned =
            """{"url":"https://box.ts.net","token":"nira_en_abc123","name":"Laptop"}"""

        val result = Pairing.parse(scanned)

        assertThat(result).isInstanceOf(Pairing.Result.Complete::class.java)
        val complete = result as Pairing.Result.Complete
        assertThat(complete.url).isEqualTo("https://box.ts.net")
        assertThat(complete.token).isEqualTo("nira_en_abc123")
        assertThat(complete.name).isEqualTo("Laptop")
    }

    @Test
    fun `accepts a bare token typed by hand`() {
        // A QR is not always scannable: a headless desktop over SSH, a broken
        // camera, a screen the phone cannot be pointed at.
        val result = Pairing.parse("nira_en_abc123")

        assertThat(result).isInstanceOf(Pairing.Result.TokenOnly::class.java)
        assertThat((result as Pairing.Result.TokenOnly).token).isEqualTo("nira_en_abc123")
    }

    @Test
    fun `trims surrounding whitespace from a pasted token`() {
        val result = Pairing.parse("  nira_en_abc123\n")

        assertThat(result).isInstanceOf(Pairing.Result.TokenOnly::class.java)
    }

    @Test
    fun `rejects an unrelated QR code`() {
        val result = Pairing.parse("https://example.com/some-other-thing")

        assertThat(result).isInstanceOf(Pairing.Result.Invalid::class.java)
    }

    @Test
    fun `rejects a payload with no token`() {
        val result = Pairing.parse("""{"url":"https://box.ts.net","token":""}""")

        assertThat(result).isInstanceOf(Pairing.Result.Invalid::class.java)
    }

    @Test
    fun `rejects a payload with no address`() {
        val result = Pairing.parse("""{"url":"","token":"nira_en_abc"}""")

        assertThat(result).isInstanceOf(Pairing.Result.Invalid::class.java)
    }

    @Test
    fun `rejects malformed json rather than crashing`() {
        assertThat(Pairing.parse("{not json"))
            .isInstanceOf(Pairing.Result.Invalid::class.java)
    }

    @Test
    fun `rejects an empty scan`() {
        assertThat(Pairing.parse("   ")).isInstanceOf(Pairing.Result.Invalid::class.java)
    }

    @Test
    fun `a bare host defaults to https`() {
        // Defaulting to http would silently downgrade a connection carrying a
        // device key, and the desktop needs TLS for the web app anyway.
        assertThat(Pairing.normaliseUrl("box.ts.net")).isEqualTo("https://box.ts.net")
    }

    @Test
    fun `an explicit scheme is respected`() {
        assertThat(Pairing.normaliseUrl("http://192.168.1.5:8000"))
            .isEqualTo("http://192.168.1.5:8000")
    }

    @Test
    fun `a trailing slash is dropped`() {
        // It would otherwise produce doubled slashes in every request path.
        assertThat(Pairing.normaliseUrl("https://box.ts.net/")).isEqualTo("https://box.ts.net")
    }

    @Test
    fun `an address with whitespace is rejected`() {
        assertThat(Pairing.normaliseUrl("box .ts.net")).isNull()
    }

    @Test
    fun `an empty address is rejected`() {
        assertThat(Pairing.normaliseUrl("   ")).isNull()
    }
}
