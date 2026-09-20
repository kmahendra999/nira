package com.nira.android.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.nira.android.data.Desktop
import com.nira.android.data.DesktopRegistry
import com.nira.android.data.Reachability
import com.nira.android.net.NiraClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class DesktopsState(
    val desktops: List<Desktop> = emptyList(),
    val selectedId: String? = null,
    val reachability: Map<String, Reachability> = emptyMap(),
    val checking: Boolean = false,
    /** Whether the background watcher is switched on. */
    val watching: Boolean = false,
)

class DesktopsViewModel(private val registry: DesktopRegistry) : ViewModel() {
    private val _state = MutableStateFlow(DesktopsState())
    val state: StateFlow<DesktopsState> = _state.asStateFlow()

    init {
        reload()
    }

    fun reload() {
        _state.value = _state.value.copy(
            desktops = registry.all(),
            selectedId = registry.selected()?.id,
            watching = registry.watchesInBackground(),
        )
        refreshReachability()
    }

    fun select(id: String) {
        registry.select(id)
        _state.value = _state.value.copy(selectedId = id)
    }

    /**
     * Open a desktop to talk to it.
     *
     * Selecting and opening are the same action. Keeping them apart meant
     * tapping one desktop opened a conversation with whichever was selected
     * before — every answer coming from a different machine than the one the
     * user just pointed at.
     */
    fun open(id: String): Desktop? {
        select(id)
        return _state.value.desktops.firstOrNull { it.id == id }
    }

    fun forget(id: String) {
        registry.remove(id)
        reload()
    }

    /**
     * Turn background watching on or off.
     *
     * Only records the preference. Starting and stopping the service is the
     * screen's job, because a view model cannot hold a Context without
     * leaking the one thing it exists to outlive.
     */
    fun setWatching(enabled: Boolean) {
        registry.setWatchesInBackground(enabled)
        _state.value = _state.value.copy(watching = enabled)
    }

    /**
     * Probe every desktop at once.
     *
     * In parallel because these are separate machines and one that is asleep
     * should not delay reporting on the rest — sequential probing makes the
     * list feel broken when a single laptop is shut.
     */
    fun refreshReachability() {
        val desktops = _state.value.desktops
        if (desktops.isEmpty()) return
        _state.value = _state.value.copy(checking = true)
        viewModelScope.launch {
            val results = withContext(Dispatchers.IO) {
                desktops.map { desktop ->
                    async {
                        desktop.id to runCatching {
                            NiraClient(desktop.baseUrl, desktop.deviceKey).info()
                        }.fold(
                            onSuccess = { Reachability.Online(it) },
                            onFailure = {
                                Reachability.Offline(it.message ?: "Unreachable")
                            },
                        )
                    }
                }.awaitAll()
            }
            _state.value = _state.value.copy(
                reachability = results.toMap(),
                checking = false,
            )
        }
    }
}
