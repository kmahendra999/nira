package com.nira.android.watch

import com.nira.android.data.AgentEvent

/**
 * What, if anything, to put in front of the user for one desktop event.
 *
 * Separate from the service that posts it so the decisions are testable
 * without a device. The decisions are the part worth testing: a notification
 * that fires twice, or that fires for something nobody can act on, trains
 * people to swipe the next one away without reading it — which is worse than
 * not notifying at all, because the one that matters looks the same.
 */
sealed interface Alert {
    /** Stable across duplicates of the same underlying thing. */
    val key: String

    /**
     * A run is parked until someone answers.
     *
     * The only alert that is urgent, because nothing proceeds without it and
     * it expires: silence eventually becomes a refusal.
     */
    data class NeedsApproval(
        val approvalId: String,
        val desktopId: String,
        val desktopName: String,
        val summary: String,
        val tool: String,
    ) : Alert {
        override val key: String get() = "approval:$desktopId:$approvalId"
    }

    /** Work that was started and has now stopped. */
    data class RunFinished(
        val desktopId: String,
        val desktopName: String,
        val agent: String,
        val failed: Boolean,
    ) : Alert {
        override val key: String get() = "run:$desktopId:$agent"
    }
}

/**
 * Decides what an event is worth telling the user about.
 *
 * Deliberately narrow. Tool calls, tokens and phase changes all stream past
 * while a run works, and a notification for each would be a stream of noise
 * about something the user already chose to start. Only two things are worth
 * interrupting for: something is blocked on you, and something you started has
 * finished.
 */
class Alerts(private val alreadySeen: MutableSet<String> = mutableSetOf()) {

    fun consider(
        event: AgentEvent,
        desktopId: String,
        desktopName: String,
    ): Alert? {
        val alert = when (event.type) {
            "approval_requested" -> approval(event, desktopId, desktopName)
            "agent_tick_end" -> finished(event, desktopId, desktopName, failed = false)
            "agent_tick_error" -> finished(event, desktopId, desktopName, failed = true)
            // A decision made elsewhere is not news — it is the reason to take
            // the old notification down, which the service does with `key`.
            else -> null
        } ?: return null

        // The same approval arrives again on every reconnect, because resuming
        // from a cursor replays what was missed. Re-posting it would buzz the
        // phone each time it changed network.
        if (!alreadySeen.add(alert.key)) return null
        return alert
    }

    /**
     * The alert key an event cancels, if it cancels one.
     *
     * A decision may be made at the desktop, or on another phone. Leaving the
     * notification up would invite an answer to a question already settled,
     * and the second tap would fail with a stale-id error that looks like the
     * app is broken.
     */
    fun resolves(event: AgentEvent, desktopId: String): String? {
        if (event.type != "approval_decided") return null
        val id = event.text("id") ?: return null
        return "approval:$desktopId:$id"
    }

    /** Forget a key so a genuinely new instance can alert again. */
    fun clear(key: String) {
        alreadySeen.remove(key)
    }

    fun forgetAll() {
        alreadySeen.clear()
    }

    private fun approval(
        event: AgentEvent,
        desktopId: String,
        desktopName: String,
    ): Alert? {
        val id = event.text("id") ?: return null
        return Alert.NeedsApproval(
            approvalId = id,
            desktopId = desktopId,
            desktopName = desktopName,
            summary = event.text("description")
                ?: event.tool?.let { "$it wants to run" }
                ?: "A step needs your approval",
            tool = event.tool ?: event.text("tool").orEmpty(),
        )
    }

    private fun finished(
        event: AgentEvent,
        desktopId: String,
        desktopName: String,
        failed: Boolean,
    ): Alert = Alert.RunFinished(
        desktopId = desktopId,
        desktopName = desktopName,
        agent = event.agent ?: "An agent",
        failed = failed,
    )
}

private fun AgentEvent.text(field: String): String? =
    (data[field] as? kotlinx.serialization.json.JsonPrimitive)
        ?.contentOrNull
        ?.takeIf { it.isNotBlank() }

private val kotlinx.serialization.json.JsonPrimitive.contentOrNull: String?
    get() = if (isString) content else content.ifEmpty { null }
