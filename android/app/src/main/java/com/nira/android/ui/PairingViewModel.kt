package com.nira.android.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.nira.android.data.Desktop
import com.nira.android.data.DesktopRegistry
import com.nira.android.data.Pairing
import com.nira.android.net.NiraClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class PairingState(
    val busy: Boolean = false,
    val error: String? = null,
    val pairedName: String? = null,
    /** Set when a scan carried a token but no address, so we must ask. */
    val awaitingAddressFor: String? = null,
)

class PairingViewModel(private val registry: DesktopRegistry) : ViewModel() {
    private val _state = MutableStateFlow(PairingState())
    val state: StateFlow<PairingState> = _state.asStateFlow()

    fun onScanned(raw: String) {
        when (val parsed = Pairing.parse(raw)) {
            is Pairing.Result.Complete -> pair(parsed.url, parsed.token, parsed.name)
            is Pairing.Result.TokenOnly ->
                _state.value = PairingState(awaitingAddressFor = parsed.token)
            is Pairing.Result.Invalid ->
                _state.value = PairingState(error = parsed.reason)
        }
    }

    fun pairManually(address: String, token: String) {
        val url = Pairing.normaliseUrl(address)
        if (url == null) {
            _state.value = _state.value.copy(error = "That address does not look right")
            return
        }
        if (!Pairing.looksLikeToken(token.trim())) {
            _state.value = _state.value.copy(error = "That pairing code does not look right")
            return
        }
        pair(url, token.trim(), "")
    }

    fun dismissError() {
        _state.value = _state.value.copy(error = null)
    }

    private fun pair(url: String, token: String, fallbackName: String) {
        _state.value = PairingState(busy = true)
        viewModelScope.launch {
            val outcome = withContext(Dispatchers.IO) {
                runCatching { NiraClient(url).enroll(token) }
            }
            outcome
                .onSuccess { enrolled ->
                    registry.save(
                        Desktop(
                            id = enrolled.deviceId,
                            name = enrolled.name.ifBlank { fallbackName.ifBlank { url } },
                            baseUrl = url,
                            deviceKey = enrolled.key,
                            scopes = enrolled.scopes,
                        )
                    )
                    _state.value = PairingState(pairedName = enrolled.name)
                }
                .onFailure { error ->
                    _state.value = PairingState(
                        error = error.message ?: "Could not pair with that desktop"
                    )
                }
        }
    }
}
