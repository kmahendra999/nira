package com.nira.android.ui.screens

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.nira.android.data.Desktop
import com.nira.android.data.Reachability
import com.nira.android.ui.DesktopsViewModel
import com.nira.android.watch.WatchService

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DesktopsScreen(
    viewModel: DesktopsViewModel,
    onPair: () -> Unit,
    onOpen: (Desktop) -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val context = LocalContext.current

    // Android 13 and up will not show a notification without this, and a
    // watcher that cannot notify is a battery cost with nothing in return.
    val askToNotify = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) {
            WatchService.start(context)
        } else {
            viewModel.setWatching(false)
        }
    }

    // Re-read on every return to this screen. The view model outlives a trip
    // to the pairing screen, so without this a desktop the user just paired
    // would be missing from the list they are sent back to.
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { viewModel.reload() }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Desktops") },
                actions = {
                    IconButton(onClick = viewModel::refreshReachability) {
                        if (state.checking) {
                            CircularProgressIndicator(Modifier.height(20.dp), strokeWidth = 2.dp)
                        } else {
                            Icon(Icons.Default.Refresh, contentDescription = "Check again")
                        }
                    }
                },
            )
        },
        floatingActionButton = {
            ExtendedFloatingActionButton(
                onClick = onPair,
                icon = { Icon(Icons.Default.Add, contentDescription = null) },
                text = { Text("Pair") },
            )
        },
    ) { padding ->
        if (state.desktops.isEmpty()) {
            EmptyDesktops(Modifier.padding(padding), onPair)
            return@Scaffold
        }

        Column(Modifier.fillMaxSize().padding(padding)) {
            WatchToggle(
                enabled = state.watching,
                onChange = { wanted ->
                    viewModel.setWatching(wanted)
                    if (!wanted) {
                        WatchService.stop(context)
                    } else if (
                        Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
                        ContextCompat.checkSelfPermission(
                            context, Manifest.permission.POST_NOTIFICATIONS
                        ) == PackageManager.PERMISSION_GRANTED
                    ) {
                        WatchService.start(context)
                    } else {
                        askToNotify.launch(Manifest.permission.POST_NOTIFICATIONS)
                    }
                },
            )

            LazyColumn(
                modifier = Modifier.fillMaxSize().padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                items(state.desktops, key = { it.id }) { desktop ->
                    DesktopCard(
                        desktop = desktop,
                        selected = desktop.id == state.selectedId,
                        reachability = state.reachability[desktop.id]
                            ?: Reachability.Unknown,
                        onSelect = { viewModel.select(desktop.id) },
                        onOpen = { viewModel.open(desktop.id)?.let(onOpen) },
                        onForget = { viewModel.forget(desktop.id) },
                    )
                }
            }
        }
    }
}

@Composable
private fun WatchToggle(enabled: Boolean, onChange: (Boolean) -> Unit) {
    Surface(
        color = MaterialTheme.colorScheme.surfaceVariant,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
        shape = MaterialTheme.shapes.medium,
    ) {
        Row(
            Modifier.padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text("Watch in the background", style = MaterialTheme.typography.titleSmall)
                Text(
                    // The cost, stated. An approval that expires unanswered
                    // becomes a refusal, which is the reason to accept it.
                    "Keeps listening while the app is closed, so an approval " +
                        "reaches you before it expires. Uses battery and shows " +
                        "a permanent notification.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Switch(checked = enabled, onCheckedChange = onChange)
        }
    }
}

@Composable
private fun EmptyDesktops(modifier: Modifier, onPair: () -> Unit) {
    Column(
        modifier = modifier.fillMaxSize().padding(32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("No desktops paired", style = MaterialTheme.typography.titleMedium)
        Spacer(Modifier.height(8.dp))
        Text(
            "Run ‘nira device pair’ on your computer, then scan the code it shows.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(16.dp))
        TextButton(onClick = onPair) { Text("Pair a desktop") }
    }
}

@Composable
private fun DesktopCard(
    desktop: Desktop,
    selected: Boolean,
    reachability: Reachability,
    onSelect: () -> Unit,
    onOpen: () -> Unit,
    onForget: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onOpen),
        colors = CardDefaults.cardColors(
            containerColor = if (selected) {
                MaterialTheme.colorScheme.surfaceVariant
            } else {
                MaterialTheme.colorScheme.surface
            },
        ),
    ) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(desktop.name, style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.width(8.dp))
                if (selected) {
                    Icon(
                        Icons.Default.Check,
                        contentDescription = "Selected",
                        tint = MaterialTheme.colorScheme.primary,
                    )
                }
            }
            Text(
                desktop.baseUrl,
                style = MaterialTheme.typography.bodySmall,
                fontFamily = FontFamily.Monospace,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(8.dp))
            ReachabilityLine(reachability)
            Spacer(Modifier.height(4.dp))
            // Scopes are worth showing: a phone that cannot approve should not
            // look like one that can and is failing.
            Text(
                "Can: ${desktop.scopes.joinToString(", ").ifBlank { "nothing" }}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (!selected) TextButton(onClick = onSelect) { Text("Use this one") }
                TextButton(onClick = onForget) { Text("Forget") }
            }
        }
    }
}

@Composable
private fun ReachabilityLine(reachability: Reachability) {
    val (text, colour) = when (reachability) {
        is Reachability.Online ->
            "Online · ${reachability.info.model.ifBlank { "no model" }}" to
                MaterialTheme.colorScheme.primary
        is Reachability.Offline ->
            reachability.reason to MaterialTheme.colorScheme.error
        Reachability.Unknown -> "Checking…" to MaterialTheme.colorScheme.onSurfaceVariant
    }
    Text(text, style = MaterialTheme.typography.bodySmall, color = colour)
}
