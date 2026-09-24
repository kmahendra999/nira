package com.nira.android.data

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * Deciding whether an install is out of date.
 *
 * The apk is sideloaded from a GitHub release, so nothing notices a new
 * version on the reader's behalf. That makes this comparison the whole
 * feature, and comparison is where update checks go wrong: `"0.1.10"` sorts
 * before `"0.1.9"` as text and after it as a version, and the mistake stays
 * invisible until the tenth patch.
 */
class AppVersionTest {

    @Test
    fun `parses a release tag and a bare version alike`() {
        assertThat(AppVersion.parse("v0.1.1")).isEqualTo(AppVersion(0, 1, 1))
        assertThat(AppVersion.parse("0.1.1")).isEqualTo(AppVersion(0, 1, 1))
        assertThat(AppVersion.parse("  v2.0.0  ")).isEqualTo(AppVersion(2, 0, 0))
    }

    @Test
    fun `missing components are zero`() {
        assertThat(AppVersion.parse("v1")).isEqualTo(AppVersion(1, 0, 0))
        assertThat(AppVersion.parse("1.2")).isEqualTo(AppVersion(1, 2, 0))
    }

    @Test
    fun `keeps a pre-release suffix`() {
        assertThat(AppVersion.parse("1.0.0-rc1")?.preRelease).isEqualTo("rc1")
        assertThat(AppVersion.parse("0.0.0-dev")?.preRelease).isEqualTo("dev")
        assertThat(AppVersion.parse("1.0.0")?.isPreRelease).isFalse()
    }

    @Test
    fun `refuses what is not a version`() {
        assertThat(AppVersion.parse(null)).isNull()
        assertThat(AppVersion.parse("")).isNull()
        assertThat(AppVersion.parse("   ")).isNull()
        assertThat(AppVersion.parse("latest")).isNull()
        assertThat(AppVersion.parse("desktop-edge")).isNull()
    }

    @Test
    fun `compares numerically, not as text`() {
        // The bug this whole class exists to avoid.
        assertThat(AppVersion.parse("0.1.10")!!)
            .isGreaterThan(AppVersion.parse("0.1.9")!!)
        assertThat(AppVersion.parse("0.10.0")!!)
            .isGreaterThan(AppVersion.parse("0.9.0")!!)
        assertThat(AppVersion.parse("10.0.0")!!)
            .isGreaterThan(AppVersion.parse("9.0.0")!!)
    }

    @Test
    fun `a pre-release precedes the release it leads to`() {
        assertThat(AppVersion.parse("1.0.0-rc1")!!)
            .isLessThan(AppVersion.parse("1.0.0")!!)
        assertThat(AppVersion.parse("0.0.0-dev")!!)
            .isLessThan(AppVersion.parse("0.0.0")!!)
    }

    @Test
    fun `a dev build is older than every release`() {
        val dev = AppVersion.parse("0.0.0-dev")!!
        assertThat(dev).isLessThan(AppVersion.parse("0.1.0")!!)
        assertThat(dev).isLessThan(AppVersion.parse("0.1.1")!!)
    }

    @Test
    fun `equal versions compare equal`() {
        assertThat(AppVersion.parse("v1.2.3")).isEqualTo(AppVersion.parse("1.2.3"))
    }

    @Test
    fun `renders back to the string it came from`() {
        assertThat(AppVersion.parse("1.2.3").toString()).isEqualTo("1.2.3")
        assertThat(AppVersion.parse("1.0.0-rc1").toString()).isEqualTo("1.0.0-rc1")
    }
}

class DecideUpdateTest {

    private fun release(tag: String) = Release(
        tag = tag,
        version = AppVersion.parse(tag)!!,
        apkUrl = "https://example.invalid/$tag/nira-android.apk",
        pageUrl = "https://example.invalid/$tag",
    )

    @Test
    fun `offers a newer release`() {
        val status = decideUpdate("0.1.0", release("v0.1.1"))

        assertThat(status).isInstanceOf(UpdateStatus.Available::class.java)
        assertThat((status as UpdateStatus.Available).release.tag).isEqualTo("v0.1.1")
    }

    @Test
    fun `says nothing when the installed build is current`() {
        assertThat(decideUpdate("0.1.1", release("v0.1.1")))
            .isEqualTo(UpdateStatus.UpToDate)
    }

    @Test
    fun `says nothing when the installed build is newer`() {
        // Someone running a local build should not be told to downgrade.
        assertThat(decideUpdate("0.2.0", release("v0.1.1")))
            .isEqualTo(UpdateStatus.UpToDate)
    }

    @Test
    fun `a dev build is offered the latest release`() {
        assertThat(decideUpdate("0.0.0-dev", release("v0.1.1")))
            .isInstanceOf(UpdateStatus.Available::class.java)
    }

    @Test
    fun `no answer from the network is not an update`() {
        assertThat(decideUpdate("0.1.0", null)).isEqualTo(UpdateStatus.Unknown)
    }

    @Test
    fun `an unreadable installed version does not nag`() {
        // Far likelier to be a build of ours we did not anticipate than a
        // genuine upgrade, and being wrong here means prompting forever.
        assertThat(decideUpdate("not-a-version", release("v0.1.1")))
            .isEqualTo(UpdateStatus.Unknown)
    }

    @Test
    fun `a dismissed release is not offered again`() {
        assertThat(decideUpdate("0.1.0", release("v0.1.1"), dismissedTag = "v0.1.1"))
            .isEqualTo(UpdateStatus.UpToDate)
    }

    @Test
    fun `dismissing one release does not opt out of the next`() {
        // Saying no once must not mean never being told again.
        val status = decideUpdate("0.1.0", release("v0.1.2"), dismissedTag = "v0.1.1")

        assertThat(status).isInstanceOf(UpdateStatus.Available::class.java)
    }
}
