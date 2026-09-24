package com.nira.android.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.nira.android.data.Release
import com.nira.android.data.SecretStore
import com.nira.android.data.UpdateStatus
import com.nira.android.data.decideUpdate
import com.nira.android.net.UpdateClient
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * Whether a newer build exists, and whether to say so.
 *
 * The apk is sideloaded from a GitHub release: there is no store to notice a
 * new version on the reader's behalf, so an old install stays old and silent
 * until somebody happens to look at the releases page.
 *
 * It fails quiet by design. Nothing here is load-bearing — if the check
 * cannot reach the network, the app works exactly as it did, and saying "we
 * could not check for updates" on launch would be noise about a thing the
 * reader did not ask for.
 */
class UpdateViewModel(
    private val installedVersion: String,
    private val store: SecretStore,
    /** Injected as a function rather than a client, so a test can answer it. */
    private val fetchLatest: suspend () -> Release? = { UpdateClient().latest() },
) : ViewModel() {

    private val _status = MutableStateFlow<UpdateStatus>(UpdateStatus.UpToDate)
    val status: StateFlow<UpdateStatus> = _status.asStateFlow()

    init {
        check()
    }

    fun check() {
        viewModelScope.launch {
            val latest = fetchLatest()
            _status.value = decideUpdate(
                installedVersion = installedVersion,
                latest = latest,
                dismissedTag = store.read(KEY_DISMISSED),
            )
        }
    }

    /**
     * Stop offering this particular release.
     *
     * Recorded by tag rather than as a blanket "never ask", so declining one
     * update does not silently opt the reader out of every future one.
     */
    fun dismiss() {
        val current = _status.value
        if (current is UpdateStatus.Available) {
            store.write(KEY_DISMISSED, current.release.tag)
        }
        _status.value = UpdateStatus.UpToDate
    }

    companion object {
        const val KEY_DISMISSED = "update.dismissed_tag"
    }
}
