package com.nira.android.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.nira.android.data.AgentEvent
import com.nira.android.data.AudioCapture
import com.nira.android.data.Microphone
import com.nira.android.data.ChatTurn
import com.nira.android.data.Desktop
import com.nira.android.data.DesktopRegistry
import com.nira.android.data.Project
import com.nira.android.net.NiraClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** A message in the transcript, as shown. */
data class Turn(
    val role: String,
    val text: String,
    /** True while tokens are still arriving for this turn. */
    val streaming: Boolean = false,
)

/** Named for the state, not the hardware: `Mic` collides with the icon. */
enum class MicState { Idle, Recording, Transcribing }

data class AskState(
    val desktop: Desktop? = null,
    /** Projects this desktop knows about; empty means plain chat only. */
    val projects: List<Project> = emptyList(),
    /** When set, prompts start work in this project instead of chatting. */
    val project: Project? = null,
    val turns: List<Turn> = emptyList(),
    val sending: Boolean = false,
    val mic: MicState = MicState.Idle,
    /** Populated once the desktop says whether it can transcribe. */
    val canTranscribe: Boolean? = null,
    val micUnavailableReason: String? = null,
    /** What the desktop is doing right now, from the event socket. */
    val activity: String? = null,
    /** The project run in flight, if the last prompt started one. */
    val run: com.nira.android.data.ProjectRun? = null,
    val error: String? = null,
)

/**
 * Drives one conversation with one desktop.
 *
 * Holds the transcript in memory only. Persisting it would mean a second copy
 * of the user's conversations living on a phone, when the whole arrangement
 * exists so that the data stays on the machine they own.
 */
class AskViewModel(
    private val registry: DesktopRegistry,
    private val capture: Microphone = AudioCapture(),
) : ViewModel() {
    private val _state = MutableStateFlow(AskState())
    val state: StateFlow<AskState> = _state.asStateFlow()

    private var streamJob: Job? = null
    private var eventJob: Job? = null
    private var recordJob: Job? = null

    init {
        reload()
    }

    fun reload() {
        val desktop = registry.selected()
        val changed = desktop?.id != _state.value.desktop?.id
        _state.value = _state.value.copy(
            desktop = desktop,
            // Keep the transcript when the same desktop comes back after a
            // trip through the picker; drop it when it is a different machine,
            // because that conversation belongs to the other one.
            turns = if (changed) emptyList() else _state.value.turns,
            canTranscribe = if (changed) null else _state.value.canTranscribe,
        )
        if (desktop != null) {
            watchActivity(desktop)
            probeSpeech(desktop)
            loadProjects(desktop)
        }
    }

    /** Point prompts at a project, or back at plain chat when null. */
    fun chooseProject(project: Project?) {
        _state.value = _state.value.copy(project = project)
    }

    private fun loadProjects(desktop: Desktop) {
        viewModelScope.launch {
            val found = withContext(Dispatchers.IO) {
                runCatching { client(desktop).projects() }
            }.getOrDefault(emptyList())
            // A desktop where nobody ran `nira project add` has none. That is
            // a normal answer, so it must not read as a failure.
            _state.value = _state.value.copy(
                projects = found,
                project = found.firstOrNull { it.id == _state.value.project?.id },
            )
        }
    }

    private fun client(desktop: Desktop) = NiraClient(desktop.baseUrl, desktop.deviceKey)

    private fun probeSpeech(desktop: Desktop) {
        viewModelScope.launch {
            val health = withContext(Dispatchers.IO) {
                runCatching { client(desktop).speechHealth() }
            }.getOrNull()
            _state.value = _state.value.copy(
                canTranscribe = health?.available ?: false,
                micUnavailableReason = when {
                    health == null -> "Could not reach that desktop"
                    health.available -> null
                    else -> health.reason ?: "No speech backend is configured on that desktop"
                },
            )
        }
    }

    /**
     * Follow what the desktop is doing, reconnecting when the socket drops.
     *
     * A phone loses this constantly — screen off, cell handover, a walk out of
     * Wi-Fi range. Without the retry the activity line goes quiet after the
     * first drop and stays quiet, which reads as "the desktop stopped working"
     * rather than "the phone stopped listening".
     */
    private fun watchActivity(desktop: Desktop) {
        eventJob?.cancel()
        if (!desktop.can("watch")) return
        eventJob = viewModelScope.launch {
            var since: Long? = null
            var backoffMs = 1_000L
            while (isActive) {
                client(desktop).agentEvents(since = since)
                    .catch { /* fall through to the retry below */ }
                    .collect { event ->
                        event.seq?.let { since = it }
                        backoffMs = 1_000L
                        describe(event)?.let { text ->
                            _state.value = _state.value.copy(activity = text)
                        }
                    }
                if (!isActive) break
                _state.value = _state.value.copy(activity = null)
                delay(backoffMs)
                backoffMs = (backoffMs * 2).coerceAtMost(30_000L)
            }
        }
    }

    fun send(prompt: String) {
        val text = prompt.trim()
        if (text.isEmpty()) return
        val desktop = _state.value.desktop ?: run {
            _state.value = _state.value.copy(error = "Pair a desktop first")
            return
        }

        val history = _state.value.turns
            .filterNot { it.streaming }
            .map { ChatTurn(it.role, it.text) }

        _state.value = _state.value.copy(
            turns = _state.value.turns +
                Turn("user", text) +
                Turn("assistant", "", streaming = true),
            sending = true,
            error = null,
        )

        val project = _state.value.project
        if (project != null) {
            startProjectRun(desktop, project, text)
            return
        }

        streamJob?.cancel()
        streamJob = viewModelScope.launch {
            val answer = StringBuilder()
            // No flowOn here: NiraClient already moves its blocking reads off
            // the collector's thread, and a second one would only obscure that.
            client(desktop).ask(text, history)
                .catch { failure ->
                    _state.value = _state.value.copy(
                        sending = false,
                        error = failure.message ?: "The desktop did not answer",
                        turns = _state.value.turns.dropLastWhile { it.streaming },
                    )
                }
                .collect { token ->
                    answer.append(token)
                    _state.value = _state.value.copy(
                        turns = _state.value.turns.replaceStreaming(answer.toString()),
                    )
                }
            if (_state.value.sending) {
                _state.value = _state.value.copy(
                    sending = false,
                    turns = _state.value.turns.settleStreaming(),
                )
            }
        }
    }

    /**
     * Hand the prompt to the project's agent rather than the chat model.
     *
     * The reply here is not a stream of tokens but a piece of work that takes
     * minutes: the desktop acknowledges it and the progress arrives on the
     * event socket, which is why the turn settles immediately with the
     * acknowledgement rather than waiting for a result that is not coming
     * over this connection.
     */
    private fun startProjectRun(desktop: Desktop, project: Project, prompt: String) {
        streamJob?.cancel()
        streamJob = viewModelScope.launch {
            val started = withContext(Dispatchers.IO) {
                runCatching { client(desktop).startRun(project.id, prompt) }
            }
            started
                .onSuccess { run ->
                    _state.value = _state.value.copy(
                        sending = false,
                        run = run,
                        turns = _state.value.turns.replaceStreaming(
                            "Working on ${project.name}\u2026"
                        ).settleStreaming(),
                    )
                    awaitRun(desktop, run.id, project.name)
                }
                .onFailure { failure ->
                    _state.value = _state.value.copy(
                        sending = false,
                        error = failure.message ?: "Could not start that work",
                        turns = _state.value.turns.dropLastWhile { it.streaming },
                    )
                }
        }
    }

    /**
     * Poll until the run finishes, then show what it did.
     *
     * Polling rather than waiting on the event socket because the events say
     * what the agent is doing, not what it concluded — and a device without
     * the "watch" scope has no socket at all, but can still be told how the
     * work it started turned out.
     */
    private suspend fun awaitRun(desktop: Desktop, runId: String, projectName: String) {
        var delayMs = 2_000L
        while (currentCoroutineContext().isActive) {
            delay(delayMs)
            delayMs = (delayMs * 2).coerceAtMost(15_000L)
            val run = withContext(Dispatchers.IO) {
                runCatching { client(desktop).run(runId) }
            }.getOrNull() ?: continue
            _state.value = _state.value.copy(run = run)
            if (!run.finished) continue
            val summary = when {
                run.result.isNotBlank() -> run.result
                run.error.isNotBlank() -> "That run failed: ${run.error}"
                else -> "Finished working on $projectName."
            }
            _state.value = _state.value.copy(
                run = run,
                turns = _state.value.turns + Turn("assistant", summary),
            )
            return
        }
    }

    fun stopStreaming() {
        streamJob?.cancel()
        _state.value = _state.value.copy(
            sending = false,
            turns = _state.value.turns.settleStreaming(),
        )
    }

    /** Begin recording. Returns immediately; the take ends at [stopRecording]. */
    fun startRecording() {
        if (_state.value.mic != MicState.Idle) return
        val desktop = _state.value.desktop ?: return
        _state.value = _state.value.copy(mic = MicState.Recording, error = null)
        recordJob = viewModelScope.launch {
            val wav = withContext(Dispatchers.IO) { capture.record() }
            if (wav == null) {
                _state.value = _state.value.copy(
                    mic = MicState.Idle,
                    error = "Nothing was recorded — hold the button while you speak",
                )
                return@launch
            }
            _state.value = _state.value.copy(mic = MicState.Transcribing)
            val heard = withContext(Dispatchers.IO) {
                runCatching { client(desktop).transcribe(wav) }
            }
            _state.value = _state.value.copy(mic = MicState.Idle)
            heard
                .onSuccess { transcript ->
                    val said = transcript.text.trim()
                    if (said.isEmpty()) {
                        _state.value = _state.value.copy(error = "Could not make that out")
                    } else {
                        send(said)
                    }
                }
                .onFailure { failure ->
                    _state.value = _state.value.copy(
                        error = failure.message ?: "Could not transcribe that"
                    )
                }
        }
    }

    fun stopRecording() {
        capture.stop()
    }

    fun micLevel(): Float = capture.level

    fun dismissError() {
        _state.value = _state.value.copy(error = null)
    }

    override fun onCleared() {
        capture.stop()
        recordJob?.cancel()
        super.onCleared()
    }

    private fun List<Turn>.replaceStreaming(text: String): List<Turn> =
        if (isEmpty() || !last().streaming) this
        else dropLast(1) + last().copy(text = text)

    private fun List<Turn>.settleStreaming(): List<Turn> =
        if (isEmpty() || !last().streaming) this
        else dropLast(1) + last().copy(streaming = false)

    private companion object {
        /** Turn an event into one line, or null when it says nothing useful. */
        fun describe(event: AgentEvent): String? = when (event.type) {
            "tool_call_start" -> event.tool?.let { "Running $it" } ?: "Running a tool"
            "tool_call_end" -> "Finished"
            "inference_start" -> "Thinking"
            "inference_end" -> null
            "agent_tick_start" -> event.agent?.let { "$it is working" } ?: "An agent is working"
            "agent_tick_end", "agent_tick_error" -> null
            else -> null
        }
    }
}
