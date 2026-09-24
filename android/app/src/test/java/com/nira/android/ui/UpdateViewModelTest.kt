package com.nira.android.ui

import com.google.common.truth.Truth.assertThat
import com.nira.android.data.AppVersion
import com.nira.android.data.InMemorySecretStore
import com.nira.android.data.Release
import com.nira.android.data.UpdateStatus
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Before
import org.junit.Test

/**
 * Being told about a new version, and being able to stop being told.
 *
 * Declining an update has to be remembered, or the same bar returns on the
 * next launch and the reader learns to ignore it — which also means ignoring
 * the one after, the one that mattered.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class UpdateViewModelTest {

    private val dispatcher = StandardTestDispatcher()

    @Before fun setUp() = Dispatchers.setMain(dispatcher)

    @After fun tearDown() = Dispatchers.resetMain()

    private fun release(tag: String) = Release(
        tag = tag,
        version = AppVersion.parse(tag)!!,
        apkUrl = "https://example.invalid/$tag/nira-android.apk",
        pageUrl = "https://example.invalid/$tag",
    )

    @Test
    fun `offers a newer release`() = runTest(dispatcher) {
        val model = UpdateViewModel("0.1.0", InMemorySecretStore()) { release("v0.1.1") }
        advanceUntilIdle()

        assertThat(model.status.value).isInstanceOf(UpdateStatus.Available::class.java)
    }

    @Test
    fun `says nothing when current`() = runTest(dispatcher) {
        val model = UpdateViewModel("0.1.1", InMemorySecretStore()) { release("v0.1.1") }
        advanceUntilIdle()

        assertThat(model.status.value).isEqualTo(UpdateStatus.UpToDate)
    }

    @Test
    fun `a network failure is silent`() = runTest(dispatcher) {
        // Nothing here is load-bearing. Failing to check must leave the app
        // exactly as it was, not report an error the reader did not ask for.
        val model = UpdateViewModel("0.1.0", InMemorySecretStore()) { null }
        advanceUntilIdle()

        assertThat(model.status.value).isEqualTo(UpdateStatus.Unknown)
    }

    @Test
    fun `dismissing records the tag and clears the bar`() = runTest(dispatcher) {
        val store = InMemorySecretStore()
        val model = UpdateViewModel("0.1.0", store) { release("v0.1.1") }
        advanceUntilIdle()

        model.dismiss()

        assertThat(model.status.value).isEqualTo(UpdateStatus.UpToDate)
        assertThat(store.read(UpdateViewModel.KEY_DISMISSED)).isEqualTo("v0.1.1")
    }

    /** The store as a previous launch's dismissal would have left it. */
    private fun storeWithDismissed(tag: String) =
        InMemorySecretStore().apply { write(UpdateViewModel.KEY_DISMISSED, tag) }

    @Test
    fun `a dismissed release is not offered on the next launch`() = runTest(dispatcher) {
        val model = UpdateViewModel("0.1.0", storeWithDismissed("v0.1.1")) {
            release("v0.1.1")
        }
        advanceUntilIdle()

        assertThat(model.status.value).isEqualTo(UpdateStatus.UpToDate)
    }

    @Test
    fun `dismissing one release does not silence the next`() = runTest(dispatcher) {
        // Saying no to v0.1.1 must not mean never hearing about v0.1.2.
        val model = UpdateViewModel("0.1.0", storeWithDismissed("v0.1.1")) {
            release("v0.1.2")
        }
        advanceUntilIdle()

        assertThat(model.status.value).isInstanceOf(UpdateStatus.Available::class.java)
    }
}
