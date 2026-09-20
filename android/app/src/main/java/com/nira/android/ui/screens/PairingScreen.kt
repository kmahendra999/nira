package com.nira.android.ui.screens

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.nira.android.ui.PairingViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PairingScreen(
    viewModel: PairingViewModel,
    onPaired: () -> Unit,
    onBack: () -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val context = LocalContext.current

    var scanning by remember { mutableStateOf(false) }
    var address by remember { mutableStateOf("") }
    var token by remember { mutableStateOf("") }

    val cameraPermission = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted -> scanning = granted }

    // A scan that carried a token but no address still needs one; carry the
    // token forward so the user only types the part that was missing.
    LaunchedEffect(state.awaitingAddressFor) {
        state.awaitingAddressFor?.let {
            token = it
            scanning = false
        }
    }

    LaunchedEffect(state.pairedName) {
        if (state.pairedName != null) onPaired()
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Pair a desktop") },
                navigationIcon = { TextButton(onClick = onBack) { Text("Back") } },
            )
        },
    ) { padding ->
        if (scanning) {
            Box(Modifier.fillMaxSize().padding(padding)) {
                QrScanner(
                    onScanned = { raw ->
                        scanning = false
                        viewModel.onScanned(raw)
                    },
                    modifier = Modifier.fillMaxSize(),
                )
            }
            return@Scaffold
        }

        Column(
            modifier = Modifier.fillMaxSize().padding(padding).padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text(
                "On your computer run ‘nira device pair <name>’, then scan the code it shows.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            Button(
                onClick = {
                    val granted = ContextCompat.checkSelfPermission(
                        context, Manifest.permission.CAMERA
                    ) == PackageManager.PERMISSION_GRANTED
                    if (granted) scanning = true
                    else cameraPermission.launch(Manifest.permission.CAMERA)
                },
                enabled = !state.busy,
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Scan the code") }

            Text(
                "Or enter it by hand — useful for a headless machine, or when the " +
                    "camera will not cooperate.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            OutlinedTextField(
                value = address,
                onValueChange = { address = it },
                label = { Text("Address") },
                placeholder = { Text("laptop.tailnet.ts.net") },
                singleLine = true,
                enabled = !state.busy,
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = token,
                onValueChange = { token = it },
                label = { Text("Pairing code") },
                placeholder = { Text("nira_en_…") },
                singleLine = true,
                enabled = !state.busy,
                modifier = Modifier.fillMaxWidth(),
            )
            Button(
                onClick = { viewModel.pairManually(address, token) },
                enabled = !state.busy && address.isNotBlank() && token.isNotBlank(),
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Pair") }

            if (state.busy) {
                Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator(Modifier.height(28.dp))
                }
            }

            state.error?.let { message ->
                Text(message, color = MaterialTheme.colorScheme.error)
                TextButton(onClick = viewModel::dismissError) { Text("Dismiss") }
            }
        }
    }
}
