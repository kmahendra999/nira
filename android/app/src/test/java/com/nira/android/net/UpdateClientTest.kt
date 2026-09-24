package com.nira.android.net

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * Reading GitHub's answer.
 *
 * The shapes here are taken from the real `/releases/latest` response for
 * `kmahendra999/nira`, so a field renamed upstream fails this rather than
 * silently returning "no update" forever.
 */
class UpdateClientTest {

    private val client = UpdateClient()

    private val realShape = """
        {
          "tag_name": "v0.1.1",
          "name": "Nira v0.1.1",
          "prerelease": false,
          "html_url": "https://github.com/kmahendra999/nira/releases/tag/v0.1.1",
          "body": "Android - nira-android.apk, 42 MiB",
          "assets": [
            {
              "name": "nira-android.apk",
              "browser_download_url": "https://github.com/kmahendra999/nira/releases/download/v0.1.1/nira-android.apk"
            }
          ]
        }
    """.trimIndent()

    @Test
    fun `reads the tag, the page and the apk`() {
        val release = client.parse(realShape)

        assertThat(release).isNotNull()
        assertThat(release!!.tag).isEqualTo("v0.1.1")
        assertThat(release.version.toString()).isEqualTo("0.1.1")
        assertThat(release.apkUrl).endsWith("/v0.1.1/nira-android.apk")
        assertThat(release.pageUrl).endsWith("/releases/tag/v0.1.1")
        assertThat(release.notes).contains("42 MiB")
    }

    @Test
    fun `a release with no apk is not an update this app can offer`() {
        // A desktop-only release carries dmg and msi and nothing installable
        // on a phone. Offering it would send the reader to a download that
        // does nothing for them.
        val desktopOnly = """
            {
              "tag_name": "v0.2.0",
              "html_url": "https://example.invalid/v0.2.0",
              "assets": [
                {"name": "Nira_0.2.0_universal.dmg",
                 "browser_download_url": "https://example.invalid/a.dmg"}
              ]
            }
        """.trimIndent()

        assertThat(client.parse(desktopOnly)).isNull()
    }

    @Test
    fun `picks the apk out of a release with several assets`() {
        val mixed = """
            {
              "tag_name": "v0.3.0",
              "html_url": "https://example.invalid/v0.3.0",
              "assets": [
                {"name": "Nira.dmg", "browser_download_url": "https://example.invalid/a.dmg"},
                {"name": "nira-android.apk", "browser_download_url": "https://example.invalid/a.apk"},
                {"name": "Nira.msi", "browser_download_url": "https://example.invalid/a.msi"}
              ]
            }
        """.trimIndent()

        assertThat(client.parse(mixed)!!.apkUrl).isEqualTo("https://example.invalid/a.apk")
    }

    @Test
    fun `a tag that is not a version is refused`() {
        // `desktop-edge` is a real rolling tag in this repository. It must
        // never be read as a version, or every launch offers an "update".
        val rolling = """
            {
              "tag_name": "desktop-edge",
              "html_url": "https://example.invalid/desktop-edge",
              "assets": [
                {"name": "nira-android.apk",
                 "browser_download_url": "https://example.invalid/a.apk"}
              ]
            }
        """.trimIndent()

        assertThat(client.parse(rolling)).isNull()
    }

    @Test
    fun `malformed answers do not throw`() {
        // The check runs at launch. Anything it cannot read has to come back
        // as "no update", never as a crash on a cold start.
        assertThat(client.parse("")).isNull()
        assertThat(client.parse("not json")).isNull()
        assertThat(client.parse("[]")).isNull()
        assertThat(client.parse("""{"message":"Not Found"}""")).isNull()
        assertThat(client.parse("""{"tag_name":null,"assets":[]}""")).isNull()
    }
}
