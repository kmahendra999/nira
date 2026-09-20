package com.nira.android.ui.screens

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.nira.android.data.Project
import com.nira.android.ui.AskViewModel
import com.nira.android.ui.MicState
import com.nira.android.ui.Turn

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AskScreen(
    viewModel: AskViewModel,
    onDesktops: () -> Unit,
    onApprovals: () -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    var draft by remember { mutableStateOf("") }
    var level by remember { mutableFloatStateOf(0f) }
    val listState = rememberLazyListState()

    // Pick up a desktop chosen while this screen was in the background.
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { viewModel.reload() }

    var micGranted by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(
                context, Manifest.permission.RECORD_AUDIO
            ) == PackageManager.PERMISSION_GRANTED
        )
    }
    val askForMic = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted -> micGranted = granted }

    // Poll the level while recording. The capture runs on a background thread
    // and writes a plain field; sampling it here keeps the meter honest
    // without pushing every buffer through the state flow.
    LaunchedEffect(state.mic) {
        while (state.mic == MicState.Recording) {
            level = viewModel.micLevel()
            kotlinx.coroutines.delay(60)
        }
        level = 0f
    }

    // Follow the answer as it streams, so the newest text stays on screen.
    LaunchedEffect(state.turns.size, state.turns.lastOrNull()?.text) {
        if (state.turns.isNotEmpty()) listState.animateScrollToItem(state.turns.lastIndex)
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(state.desktop?.name ?: "No desktop") },
                actions = {
                    // Only offered when something is actually waiting. A
                    // permanent button here would be one more thing to ignore
                    // on the screen where the answer matters most.
                    if (state.awaitingApproval) {
                        TextButton(onClick = onApprovals) { Text("Approve") }
                    }
                    TextButton(onClick = onDesktops) { Text("Desktops") }
                },
            )
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            state.activity?.let { activity ->
                Surface(
                    color = if (state.awaitingApproval) {
                        MaterialTheme.colorScheme.errorContainer
                    } else {
                        MaterialTheme.colorScheme.secondaryContainer
                    },
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(
                        activity,
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp),
                        style = MaterialTheme.typography.labelMedium,
                        color = if (state.awaitingApproval) {
                            MaterialTheme.colorScheme.onErrorContainer
                        } else {
                            MaterialTheme.colorScheme.onSecondaryContainer
                        },
                    )
                }
            }

            if (state.turns.isEmpty()) {
                Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                    Text(
                        if (state.desktop == null) {
                            "Pair a desktop to start."
                        } else {
                            "Ask anything, or hold the microphone and speak."
                        },
                        textAlign = TextAlign.Center,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(32.dp),
                    )
                }
            } else {
                LazyColumn(
                    state = listState,
                    modifier = Modifier.weight(1f).fillMaxWidth(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    items(state.turns) { turn -> Bubble(turn) }
                }
            }

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

            if (state.projects.isNotEmpty()) {
                ProjectChips(
                    projects = state.projects,
                    chosen = state.project,
                    onChoose = viewModel::chooseProject,
                )
            }

            Row(
                Modifier.fillMaxWidth().padding(12.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                OutlinedTextField(
                    value = draft,
                    onValueChange = { draft = it },
                    placeholder = {
                        Text(
                            when (state.mic) {
                                MicState.Recording -> "Listening…"
                                MicState.Transcribing -> "Working out what you said…"
                                MicState.Idle -> "Ask your desktop"
                            }
                        )
                    },
                    enabled = state.mic == MicState.Idle && state.desktop != null,
                    modifier = Modifier.weight(1f),
                    maxLines = 4,
                )

                if (state.canTranscribe == true && state.desktop != null) {
                    MicButton(
                        recording = state.mic == MicState.Recording,
                        busy = state.mic == MicState.Transcribing,
                        level = level,
                        onPress = {
                            if (micGranted) viewModel.startRecording()
                            else askForMic.launch(Manifest.permission.RECORD_AUDIO)
                        },
                        onRelease = viewModel::stopRecording,
                    )
                }

                IconButton(
                    onClick = {
                        if (state.sending) {
                            viewModel.stopStreaming()
                        } else {
                            viewModel.send(draft)
                            draft = ""
                        }
                    },
                    enabled = state.desktop != null && (state.sending || draft.isNotBlank()),
                ) {
                    if (state.sending) {
                        CircularProgressIndicator(Modifier.size(20.dp))
                    } else {
                        Icon(Icons.AutoMirrored.Filled.Send, contentDescription = "Send")
                    }
                }
            }

            // Only explain a missing microphone once we know it is missing —
            // before the probe answers, canTranscribe is null and saying
            // anything would be a guess.
            if (state.canTranscribe == false && state.desktop != null) {
                Text(
                    state.micUnavailableReason ?: "Voice is not available on that desktop",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = 16.dp).padding(bottom = 12.dp),
                )
            }
        }
    }
}

/**
 * Where the next prompt goes.
 *
 * Shown as a row rather than hidden in a menu because it changes what the
 * prompt *does* — chat answers a question, a project sends an agent into a
 * directory with file and shell access. That is not a setting to bury.
 */
@Composable
private fun ProjectChips(
    projects: List<Project>,
    chosen: Project?,
    onChoose: (Project?) -> Unit,
) {
    LazyRow(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(horizontal = 12.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        item {
            FilterChip(
                selected = chosen == null,
                onClick = { onChoose(null) },
                label = { Text("Chat") },
            )
        }
        items(projects, key = { it.id }) { project ->
            FilterChip(
                selected = chosen?.id == project.id,
                onClick = { onChoose(project) },
                label = { Text(project.name) },
            )
        }
    }
}

@Composable
private fun MicButton(
    recording: Boolean,
    busy: Boolean,
    level: Float,
    onPress: () -> Unit,
    onRelease: () -> Unit,
) {
    Box(
        contentAlignment = Alignment.Center,
        modifier = Modifier
            .size(48.dp)
            .pointerInput(busy) {
                if (busy) return@pointerInput
                detectTapGestures(
                    onPress = {
                        onPress()
                        // Hold to talk: the take ends when the finger lifts,
                        // including when the gesture is cancelled by a scroll,
                        // so a stray swipe cannot leave the mic open.
                        tryAwaitRelease()
                        onRelease()
                    }
                )
            },
    ) {
        if (busy) {
            CircularProgressIndicator(Modifier.size(24.dp))
            return@Box
        }
        Box(
            Modifier
                .size(40.dp)
                .scale(if (recording) 1f + level * 0.35f else 1f)
                .background(
                    if (recording) MaterialTheme.colorScheme.primary
                    else MaterialTheme.colorScheme.surfaceVariant,
                    CircleShape,
                ),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                Icons.Filled.Mic,
                contentDescription = if (recording) "Recording" else "Hold to speak",
                tint = if (recording) MaterialTheme.colorScheme.onPrimary
                else MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun Bubble(turn: Turn) {
    val mine = turn.role == "user"
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = if (mine) Arrangement.End else Arrangement.Start,
    ) {
        Surface(
            color = if (mine) MaterialTheme.colorScheme.primaryContainer
            else MaterialTheme.colorScheme.surfaceVariant,
            shape = RoundedCornerShape(
                topStart = 16.dp,
                topEnd = 16.dp,
                bottomStart = if (mine) 16.dp else 4.dp,
                bottomEnd = if (mine) 4.dp else 16.dp,
            ),
            modifier = Modifier.fillMaxWidth(0.88f),
        ) {
            Text(
                // A streaming turn starts empty; show something so the bubble
                // does not appear as a blank box while the first token lands.
                turn.text.ifEmpty { if (turn.streaming) "…" else "" },
                modifier = Modifier.padding(12.dp),
                color = if (mine) MaterialTheme.colorScheme.onPrimaryContainer
                else MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}
