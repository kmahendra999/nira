package com.nira.android.ui

import com.google.common.truth.Truth.assertThat
import com.nira.android.data.Desktop
import com.nira.android.data.DesktopRegistry
import com.nira.android.data.InMemorySecretStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class DesktopsViewModelTest {
    private lateinit var registry: DesktopRegistry

    @Before
    fun setUp() {
        Dispatchers.setMain(Dispatchers.Unconfined)
        registry = DesktopRegistry(InMemorySecretStore())
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun save(id: String) {
        registry.save(
            Desktop(
                id = id,
                name = id,
                // Unroutable on purpose: these tests are about bookkeeping,
                // and the reachability probe must not reach anything.
                baseUrl = "http://127.0.0.1:1",
                deviceKey = "nira_dk_$id",
                scopes = listOf("ask", "watch"),
            )
        )
    }

    @Test
    fun `opening a desktop selects it`() {
        save("dev_1")
        save("dev_2")
        val model = DesktopsViewModel(registry)
        assertThat(model.state.value.selectedId).isEqualTo("dev_1")

        val opened = model.open("dev_2")

        // Tapping a desktop and then talking to a different one is the bug
        // this exists to prevent.
        assertThat(opened?.id).isEqualTo("dev_2")
        assertThat(model.state.value.selectedId).isEqualTo("dev_2")
        assertThat(registry.selected()?.id).isEqualTo("dev_2")
    }

    @Test
    fun `opening a desktop that is gone selects nothing and reports nothing`() {
        save("dev_1")
        val model = DesktopsViewModel(registry)

        assertThat(model.open("dev_missing")).isNull()
    }

    @Test
    fun `the first paired desktop is selected automatically`() {
        save("dev_1")
        val model = DesktopsViewModel(registry)

        assertThat(model.state.value.desktops).hasSize(1)
        assertThat(model.state.value.selectedId).isEqualTo("dev_1")
    }

    @Test
    fun `forgetting the selected desktop falls back to another`() {
        save("dev_1")
        save("dev_2")
        val model = DesktopsViewModel(registry)
        model.open("dev_2")

        model.forget("dev_2")

        assertThat(model.state.value.desktops.map { it.id }).containsExactly("dev_1")
        // Never left pointing at a desktop that is gone.
        assertThat(model.state.value.selectedId).isEqualTo("dev_1")
    }

    @Test
    fun `forgetting the last desktop leaves nothing selected`() {
        save("dev_1")
        val model = DesktopsViewModel(registry)

        model.forget("dev_1")

        assertThat(model.state.value.desktops).isEmpty()
        assertThat(model.state.value.selectedId).isNull()
    }
}
