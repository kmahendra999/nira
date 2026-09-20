package com.nira.android.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.nira.android.data.Approval
import com.nira.android.data.Desktop
import com.nira.android.data.DesktopRegistry
import com.nira.android.net.NiraClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class ApprovalsState(
    val desktop: Desktop? = null,
    val waiting: List<Approval> = emptyList(),
    /** Ids currently being answered, so a tap cannot be double-counted. */
    val deciding: Set<String> = emptySet(),
    val loading: Boolean = false,
    /** False when this device was not granted the scope to answer. */
    val canApprove: Boolean = true,
    val error: String? = null,
)

/**
 * The queue of steps an agent is waiting on.
 *
 * This is the point of carrying the desktop in your pocket: the run is parked
 * until someone answers, and until now the only someone was whoever happened
 * to be sitting at the machine.
 */
class ApprovalsViewModel(private val registry: DesktopRegistry) : ViewModel() {
    private val _state = MutableStateFlow(ApprovalsState())
    val state: StateFlow<ApprovalsState> = _state.asStateFlow()

    private var watchJob: Job? = null

    init {
        reload()
    }

    fun reload() {
        val desktop = registry.selected()
        _state.value = _state.value.copy(
            desktop = desktop,
            canApprove = desktop?.can("approve") ?: true,
            waiting = if (desktop?.id != _state.value.desktop?.id) emptyList()
            else _state.value.waiting,
        )
        if (desktop == null) return
        refresh()
        watch(desktop)
    }

    fun refresh() {
        val desktop = _state.value.desktop ?: return
        if (!desktop.can("approve")) return
        viewModelScope.launch {
            _state.value = _state.value.copy(loading = true)
            val found = withContext(Dispatchers.IO) {
                runCatching { NiraClient(desktop.baseUrl, desktop.deviceKey).approvals() }
            }
            _state.value = found.fold(
                onSuccess = {
                    _state.value.copy(waiting = it, loading = false, error = null)
                },
                onFailure = {
                    _state.value.copy(
                        loading = false,
                        error = it.message ?: "Could not read the approval queue",
                    )
                },
            )
        }
    }

    /**
     * Follow the desktop's events so a new question arrives immediately.
     *
     * Polling would be the obvious choice and is the wrong one here: whatever
     * the interval, that is how long an agent sits parked before anyone is
     * told it is waiting — and a parked run is indistinguishable from a broken
     * one. The socket also carries decisions made elsewhere, so answering on
     * the desktop clears the question off the phone.
     */
    private fun watch(desktop: Desktop) {
        watchJob?.cancel()
        if (!desktop.can("watch")) return
        watchJob = viewModelScope.launch {
            var since: Long? = null
            var backoffMs = 1_000L
            while (isActive) {
                NiraClient(desktop.baseUrl, desktop.deviceKey)
                    .agentEvents(since = since)
                    .catch { /* fall through to the retry below */ }
                    .collect { event ->
                        event.seq?.let { since = it }
                        backoffMs = 1_000L
                        if (event.type == "approval_requested" ||
                            event.type == "approval_decided"
                        ) {
                            // Re-read rather than patch from the payload: the
                            // queue is shared, and a decision may have been
                            // made at the desktop a moment ago.
                            refresh()
                        }
                    }
                if (!isActive) break
                delay(backoffMs)
                backoffMs = (backoffMs * 2).coerceAtMost(30_000L)
            }
        }
    }

    fun decide(id: String, approve: Boolean) {
        val desktop = _state.value.desktop ?: return
        if (id in _state.value.deciding) return
        _state.value = _state.value.copy(deciding = _state.value.deciding + id)
        viewModelScope.launch {
            val outcome = withContext(Dispatchers.IO) {
                runCatching {
                    NiraClient(desktop.baseUrl, desktop.deviceKey)
                        .decideApproval(id, approve)
                }
            }
            _state.value = outcome.fold(
                onSuccess = {
                    // Drop it immediately. The run is waiting on this answer,
                    // so leaving the card on screen until the next refresh
                    // invites a second tap on a question already settled.
                    _state.value.copy(
                        waiting = _state.value.waiting.filterNot { it.id == id },
                        deciding = _state.value.deciding - id,
                        error = null,
                    )
                },
                onFailure = {
                    _state.value.copy(
                        deciding = _state.value.deciding - id,
                        error = it.message ?: "That answer did not reach the desktop",
                    )
                },
            )
        }
    }

    fun dismissError() {
        _state.value = _state.value.copy(error = null)
    }
}
