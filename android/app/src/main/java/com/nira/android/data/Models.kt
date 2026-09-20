package com.nira.android.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * What `nira device pair` encodes in its QR.
 *
 * The URL matters as much as the token: a phone needs somewhere to send the
 * invitation, and on a tailnet the MagicDNS name is the one address that keeps
 * working as the desktop moves between networks.
 */
@Serializable
data class PairingPayload(
    val url: String,
    val token: String,
    val name: String = "",
)

@Serializable
data class EnrollRequest(
    val token: String,
    val platform: String = "android",
)

@Serializable
data class EnrollResponse(
    @SerialName("device_id") val deviceId: String,
    val name: String,
    val scopes: List<String> = emptyList(),
    /** Returned exactly once; the server keeps only a hash. */
    val key: String,
)

@Serializable
data class ServerInfo(
    val model: String = "",
    val agent: String? = null,
    val engine: String = "",
)

/**
 * A paired desktop.
 *
 * One phone can be paired with several, which is why the key lives here rather
 * than in a single global setting: each desktop issues its own, and revoking
 * one must not affect the others.
 */
@Serializable
data class Desktop(
    val id: String,
    val name: String,
    val baseUrl: String,
    val deviceKey: String,
    val scopes: List<String> = emptyList(),
) {
    /** True when this desktop granted [scope], or admin over everything. */
    fun can(scope: String): Boolean = scope in scopes || "admin" in scopes
}

/** Liveness of a paired desktop, as shown in the picker. */
sealed interface Reachability {
    data object Unknown : Reachability
    data class Online(val info: ServerInfo) : Reachability
    data class Offline(val reason: String) : Reachability
}

/** One frame from the agent-events socket. */
@Serializable
data class AgentEvent(
    val type: String,
    val timestamp: Double = 0.0,
    val seq: Long? = null,
    /** On `replay_start`: whether the backlog handed over was complete. */
    val gap: Boolean = false,
    val count: Int = 0,
    val data: Map<String, kotlinx.serialization.json.JsonElement> = emptyMap(),
) {
    val tool: String? get() = data["tool"]?.let(::unquote)
    val agent: String? get() = (data["agent_id"] ?: data["agent"])?.let(::unquote)

    private fun unquote(element: kotlinx.serialization.json.JsonElement): String? =
        (element as? kotlinx.serialization.json.JsonPrimitive)?.contentOrNull

    companion object {
        const val REPLAY_START = "replay_start"
        const val REPLAY_END = "replay_end"
    }
}

private val kotlinx.serialization.json.JsonPrimitive.contentOrNull: String?
    get() = if (isString) content else content.ifEmpty { null }

/** One turn of conversation, as the completions endpoint expects it. */
@Serializable
data class ChatTurn(val role: String, val content: String)

/** What the desktop heard. */
@Serializable
data class Transcript(
    val text: String = "",
    val language: String? = null,
    val confidence: Double? = null,
    @SerialName("duration_seconds") val durationSeconds: Double? = null,
)

/**
 * Whether a desktop can transcribe.
 *
 * Checked before offering the microphone: a mic button that fails only after
 * the user has finished speaking is worse than one that was never offered.
 */
@Serializable
data class SpeechHealth(
    val available: Boolean = false,
    val backend: String? = null,
    val reason: String? = null,
)

/** A directory on the desktop that the agent can be pointed at. */
@Serializable
data class Project(
    val id: String,
    val name: String,
    val path: String,
    @SerialName("default_agent") val defaultAgent: String = "",
)

@Serializable
data class ProjectList(val projects: List<Project> = emptyList())

/** One agent run against one project. Progress arrives on the event socket. */
@Serializable
data class ProjectRun(
    val id: String,
    @SerialName("project_id") val projectId: String = "",
    @SerialName("project_name") val projectName: String = "",
    val prompt: String = "",
    val status: String = "running",
    val result: String = "",
    val error: String = "",
    val turns: Int = 0,
) {
    val finished: Boolean get() = status != "running"
}

@Serializable
data class ProjectRunEnvelope(val run: ProjectRun)

/**
 * A step an agent is waiting on you to allow.
 *
 * The run is parked while this sits here: the desktop's agent has asked
 * whether it may do something and will not proceed until someone answers, or
 * until it gives up and treats the silence as no.
 */
@Serializable
data class Approval(
    val id: String,
    @SerialName("action_type") val actionType: String = "",
    val description: String = "",
    val payload: Map<String, kotlinx.serialization.json.JsonElement> = emptyMap(),
    @SerialName("permission_key") val permissionKey: String = "",
    val tier: String = "medium",
    @SerialName("created_at") val createdAt: String = "",
) {
    /** True when one yes must not become a standing yes. */
    val alwaysAsks: Boolean get() = tier == "high"

    /** The command or path at issue, when there is one worth showing. */
    val detail: String?
        get() = (payload["input"] as? kotlinx.serialization.json.JsonObject)
            ?.let { it["command"] ?: it["file_path"] }
            ?.let { (it as? kotlinx.serialization.json.JsonPrimitive)?.content }
            ?.takeIf { it.isNotBlank() }
}

@Serializable
data class ApprovalQueue(
    val actions: List<Approval> = emptyList(),
    val count: Int = 0,
)
