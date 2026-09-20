package com.nira.android.data

import com.google.common.truth.Truth.assertThat
import org.junit.Test

/**
 * One phone pairs with several desktops, each issuing its own key, and
 * revoking one must leave the others working — which a single global
 * "server URL and API key" setting cannot express.
 */
class DesktopRegistryTest {
    private fun registry() = DesktopRegistry(InMemorySecretStore())

    private fun desktop(id: String, name: String = id) = Desktop(
        id = id,
        name = name,
        baseUrl = "https://$name.ts.net",
        deviceKey = "nira_dk_$id",
        scopes = listOf("ask", "watch"),
    )

    @Test
    fun `an empty registry lists nothing`() {
        assertThat(registry().all()).isEmpty()
        assertThat(registry().selected()).isNull()
    }

    @Test
    fun `a saved desktop can be read back`() {
        val registry = registry()
        registry.save(desktop("dev_1", "laptop"))

        val stored = registry.get("dev_1")
        assertThat(stored?.name).isEqualTo("laptop")
        assertThat(stored?.deviceKey).isEqualTo("nira_dk_dev_1")
    }

    @Test
    fun `several desktops coexist with separate keys`() {
        val registry = registry()
        registry.save(desktop("dev_1", "laptop"))
        registry.save(desktop("dev_2", "workstation"))

        assertThat(registry.all()).hasSize(2)
        assertThat(registry.get("dev_1")!!.deviceKey)
            .isNotEqualTo(registry.get("dev_2")!!.deviceKey)
    }

    @Test
    fun `re-pairing replaces rather than duplicating`() {
        // Otherwise a stale key that no longer authenticates lingers next to
        // the working one, and which gets used is down to list order.
        val registry = registry()
        registry.save(desktop("dev_1", "laptop"))
        registry.save(desktop("dev_1", "laptop").copy(deviceKey = "nira_dk_fresh"))

        assertThat(registry.all()).hasSize(1)
        assertThat(registry.get("dev_1")!!.deviceKey).isEqualTo("nira_dk_fresh")
    }

    @Test
    fun `the first pairing becomes the selection`() {
        val registry = registry()
        registry.save(desktop("dev_1"))

        assertThat(registry.selected()?.id).isEqualTo("dev_1")
    }

    @Test
    fun `adding a second desktop does not steal the selection`() {
        val registry = registry()
        registry.save(desktop("dev_1"))
        registry.save(desktop("dev_2"))

        assertThat(registry.selected()?.id).isEqualTo("dev_1")
    }

    @Test
    fun `removing the selected desktop falls back to another`() {
        // The app must not be left pointing at a desktop that is gone.
        val registry = registry()
        registry.save(desktop("dev_1"))
        registry.save(desktop("dev_2"))
        registry.select("dev_1")

        registry.remove("dev_1")

        assertThat(registry.selected()?.id).isEqualTo("dev_2")
    }

    @Test
    fun `removing the last desktop leaves no selection`() {
        val registry = registry()
        registry.save(desktop("dev_1"))

        registry.remove("dev_1")

        assertThat(registry.selected()).isNull()
    }

    @Test
    fun `corrupt storage degrades to empty rather than crashing`() {
        // Losing the pairing list costs a re-pair; refusing to start costs the
        // whole app.
        val store = InMemorySecretStore(mutableMapOf("desktops" to "not json"))

        assertThat(DesktopRegistry(store).all()).isEmpty()
    }

    @Test
    fun `scopes ride along with the pairing`() {
        val registry = registry()
        registry.save(desktop("dev_1").copy(scopes = listOf("ask")))

        val stored = registry.get("dev_1")!!
        assertThat(stored.can("ask")).isTrue()
        assertThat(stored.can("approve")).isFalse()
    }

    @Test
    fun `admin implies every scope`() {
        val desktop = desktop("dev_1").copy(scopes = listOf("admin"))

        assertThat(desktop.can("approve")).isTrue()
    }

    @Test
    fun `background watching is off until it is asked for`() {
        // It costs a persistent connection, a permanent notification and
        // battery. That is a reasonable trade for someone running long agent
        // tasks and an imposition on someone who is not, so it is never the
        // default.
        assertThat(registry().watchesInBackground()).isFalse()
    }

    @Test
    fun `background watching is remembered`() {
        val registry = registry()

        registry.setWatchesInBackground(true)

        assertThat(registry.watchesInBackground()).isTrue()
    }

    @Test
    fun `background watching can be turned back off`() {
        val registry = registry()
        registry.setWatchesInBackground(true)

        registry.setWatchesInBackground(false)

        // Stored as a definite false rather than cleared, so "never asked"
        // and "asked to stop" do not have to be told apart later.
        assertThat(registry.watchesInBackground()).isFalse()
    }

    @Test
    fun `the watch preference survives pairing and forgetting desktops`() {
        val registry = registry()
        registry.setWatchesInBackground(true)

        registry.save(desktop("dev_1", "laptop"))
        registry.remove("dev_1")

        // Unpairing the last desktop is not a request to change this setting,
        // and re-pairing should not silently leave the watcher off.
        assertThat(registry.watchesInBackground()).isTrue()
    }
}
