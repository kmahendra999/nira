package com.nira.android.data

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * Projects are directories, and a directory exists on exactly one computer.
 *
 * Which one is not a label — it decides where the work runs. Sending a run to
 * the wrong machine either fails outright or, worse, finds a same-named
 * directory and edits the wrong tree.
 */
class ProjectIndexTest {
    private fun desktop(id: String, name: String = id) = Desktop(
        id = id,
        name = name,
        baseUrl = "https://$name.ts.net",
        deviceKey = "nira_dk_$id",
        scopes = listOf("ask", "watch"),
    )

    private fun project(id: String, name: String = id) =
        Project(id = id, name = name, path = "/home/u/$name")

    @Test
    fun `an empty index reports itself as empty`() {
        assertThat(ProjectIndex.of(emptyMap()).isEmpty).isTrue()
        assertThat(ProjectIndex.of(emptyMap()).spansDesktops).isFalse()
    }

    @Test
    fun `projects from several desktops end up in one list`() {
        val laptop = desktop("dev_1", "laptop")
        val studio = desktop("dev_2", "studio")

        val index = ProjectIndex.of(
            mapOf(laptop to listOf(project("p1", "nira")), studio to listOf(project("p2", "site"))),
        )

        // The whole reason for pairing more than one machine: work lives in
        // different places and should not have to be hunted for.
        assertThat(index.located.map { it.project.name })
            .containsExactly("nira", "site")
        assertThat(index.spansDesktops).isTrue()
    }

    @Test
    fun `a project carries the desktop it lives on`() {
        val studio = desktop("dev_2", "studio")

        val index = ProjectIndex.of(mapOf(studio to listOf(project("p2", "site"))))

        assertThat(index.located.single().desktop.id).isEqualTo("dev_2")
        assertThat(index.located.single().desktop.baseUrl).isEqualTo(studio.baseUrl)
    }

    @Test
    fun `the same project name on two machines stays two projects`() {
        val laptop = desktop("dev_1", "laptop")
        val studio = desktop("dev_2", "studio")

        val index = ProjectIndex.of(
            mapOf(
                laptop to listOf(project("nira", "nira")),
                studio to listOf(project("nira", "nira")),
            ),
        )

        // Two checkouts of one repo is the normal case, and collapsing them
        // would send work to whichever happened to win.
        assertThat(index.located).hasSize(2)
        assertThat(index.located.map { it.key }).containsNoDuplicates()
    }

    @Test
    fun `a key identifies one project on one machine`() {
        val laptop = desktop("dev_1", "laptop")
        val studio = desktop("dev_2", "studio")
        val index = ProjectIndex.of(
            mapOf(
                laptop to listOf(project("nira", "nira")),
                studio to listOf(project("nira", "nira")),
            ),
        )

        val onStudio = index.find("dev_2/nira")

        assertThat(onStudio).isNotNull()
        assertThat(onStudio!!.desktop.id).isEqualTo("dev_2")
    }

    @Test
    fun `an unknown key finds nothing rather than guessing`() {
        val index = ProjectIndex.of(mapOf(desktop("dev_1") to listOf(project("p1"))))

        assertThat(index.find("dev_9/p1")).isNull()
        assertThat(index.find("")).isNull()
    }

    @Test
    fun `the selected desktop comes first`() {
        val laptop = desktop("dev_1", "aaa-laptop")
        val studio = desktop("dev_2", "zzz-studio")

        val index = ProjectIndex.of(
            mapOf(laptop to listOf(project("p1", "one")), studio to listOf(project("p2", "two"))),
            selectedId = "dev_2",
        )

        // Whichever machine the user is already pointed at is the one they
        // most likely mean, even though its name sorts last.
        assertThat(index.located.first().desktop.id).isEqualTo("dev_2")
    }

    @Test
    fun `the order is stable when nothing is selected`() {
        val laptop = desktop("dev_1", "laptop")
        val studio = desktop("dev_2", "studio")
        val entries = mapOf(
            studio to listOf(project("p2", "beta")),
            laptop to listOf(project("p1", "alpha")),
        )

        val first = ProjectIndex.of(entries).located.map { it.key }
        val again = ProjectIndex.of(entries).located.map { it.key }

        // A list that reshuffles between reads is one you cannot build muscle
        // memory for.
        assertThat(first).isEqualTo(again)
        assertThat(first.first()).startsWith("dev_1")
    }

    @Test
    fun `a single desktop does not claim to span machines`() {
        val index = ProjectIndex.of(
            mapOf(desktop("dev_1") to listOf(project("p1"), project("p2"))),
        )

        // The desktop name is shown on each chip only when it disambiguates;
        // otherwise it is noise on every one of them.
        assertThat(index.spansDesktops).isFalse()
    }

    @Test
    fun `an unreachable desktop is remembered, not silently dropped`() {
        val laptop = desktop("dev_1", "laptop")
        val asleep = desktop("dev_2", "studio")

        val index = ProjectIndex.of(
            found = mapOf(laptop to listOf(project("p1"))),
            unreachable = listOf(asleep),
        )

        // "No projects on that machine" and "that machine is asleep" are
        // different facts, and only one of them means look somewhere else.
        assertThat(index.unreachable.map { it.name }).containsExactly("studio")
        assertThat(index.located).hasSize(1)
    }

    @Test
    fun `a desktop with no projects contributes nothing and is not an error`() {
        val index = ProjectIndex.of(mapOf(desktop("dev_1") to emptyList()))

        assertThat(index.isEmpty).isTrue()
        assertThat(index.unreachable).isEmpty()
    }
}
