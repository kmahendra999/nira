package com.nira.android.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.nira.android.data.Approval
import com.nira.android.ui.ApprovalsViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ApprovalsScreen(viewModel: ApprovalsViewModel, onBack: () -> Unit) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { viewModel.reload() }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Waiting on you") },
                navigationIcon = { TextButton(onClick = onBack) { Text("Back") } },
                actions = {
                    TextButton(onClick = viewModel::refresh) { Text("Refresh") }
                },
            )
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            state.error?.let { message ->
                Row(
                    Modifier.fillMaxWidth().padding(horizontal = 16.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        message,
                        color = MaterialTheme.colorScheme.error,
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.weight(1f),
                    )
                    TextButton(onClick = viewModel::dismissError) { Text("Dismiss") }
                }
            }

            when {
                state.desktop == null -> Empty("Pair a desktop first.")

                !state.canApprove -> Empty(
                    "This phone was not granted permission to approve. " +
                        "Re-pair it with the ‘approve’ scope to answer from here.",
                )

                state.waiting.isEmpty() -> Empty(
                    if (state.loading) "Checking…"
                    else "Nothing is waiting. Agents will appear here when they " +
                        "need a decision before carrying on.",
                )

                else -> LazyColumn(
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    items(state.waiting, key = { it.id }) { approval ->
                        ApprovalCard(
                            approval = approval,
                            busy = approval.id in state.deciding,
                            onDecide = { allow -> viewModel.decide(approval.id, allow) },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun Empty(message: String) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Text(
            message,
            textAlign = TextAlign.Center,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(32.dp),
        )
    }
}

@Composable
private fun ApprovalCard(
    approval: Approval,
    busy: Boolean,
    onDecide: (Boolean) -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant,
        ),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (approval.alwaysAsks) {
                // A tool that changes the world. Saying so is the difference
                // between an informed yes and a reflexive one.
                Surface(
                    color = MaterialTheme.colorScheme.errorContainer,
                    shape = MaterialTheme.shapes.small,
                ) {
                    Text(
                        "Changes files or runs commands",
                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onErrorContainer,
                    )
                }
            }

            Text(approval.description, style = MaterialTheme.typography.bodyLarge)

            // The exact command, verbatim and unwrapped-looking. Approving
            // something described only in prose is approving a summary.
            approval.detail?.let { detail ->
                Surface(
                    color = MaterialTheme.colorScheme.surface,
                    shape = MaterialTheme.shapes.small,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(
                        detail,
                        modifier = Modifier.padding(10.dp),
                        style = MaterialTheme.typography.bodySmall,
                        fontFamily = FontFamily.Monospace,
                    )
                }
            }

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                // Refusing comes first and is the plain button: the safe
                // answer should not be the one you have to aim for.
                OutlinedButton(
                    onClick = { onDecide(false) },
                    enabled = !busy,
                    modifier = Modifier.weight(1f),
                ) { Text("Refuse") }
                Button(
                    onClick = { onDecide(true) },
                    enabled = !busy,
                    modifier = Modifier.weight(1f),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = MaterialTheme.colorScheme.primary,
                    ),
                ) {
                    if (busy) CircularProgressIndicator(Modifier.size(18.dp))
                    else Text("Allow")
                }
            }
        }
    }
}
