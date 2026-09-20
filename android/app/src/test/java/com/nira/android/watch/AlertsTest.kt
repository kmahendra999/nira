package com.nira.android.watch

import com.google.common.truth.Truth.assertThat
import com.nira.android.data.AgentEvent
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Test

/**
 * What is worth interrupting someone for.
 *
 * A notification that fires twice, or fires for something nobody can act on,
 * trains people to swipe the next one away without reading it — which is worse
 * than not notifying at all, because the one that matters then looks the same
 * as the rest.
 */
class AlertsTest {
    private fun event(type: String, vararg data: Pair<String, String>) = AgentEvent(
        type = type,
        data = data.associate { (k, v) -> k to (JsonPrimitive(v) as JsonElement) },
    )

    private fun approvalRequested(id: String = "act_1") = event(
        "approval_requested",
        "id" to id,
        "tool" to "Bash",
        "description" to "Run a shell command: rm -rf build",
    )

    @Test
    fun `a waiting approval is worth an alert`() {
        val alert = Alerts().consider(approvalRequested(), "dev_1", "laptop")

        assertThat(alert).isInstanceOf(Alert.NeedsApproval::class.java)
        val needs = alert as Alert.NeedsApproval
        assertThat(needs.summary).contains("rm -rf build")
        assertThat(needs.desktopName).isEqualTo("laptop")
    }

    @Test
    fun `a finished run is worth an alert`() {
        val alert = Alerts().consider(
            event("agent_tick_end", "agent_id" to "researcher"), "dev_1", "laptop",
        )

        assertThat(alert).isInstanceOf(Alert.RunFinished::class.java)
        assertThat((alert as Alert.RunFinished).failed).isFalse()
    }

    @Test
    fun `a failed run says it failed`() {
        val alert = Alerts().consider(
            event("agent_tick_error", "agent_id" to "researcher"), "dev_1", "laptop",
        )

        assertThat((alert as Alert.RunFinished).failed).isTrue()
    }

    @Test
    fun `progress is not worth interrupting anyone for`() {
        val alerts = Alerts()

        // These stream past continuously while a run works. One notification
        // each would be a torrent of noise about something the user started
        // on purpose.
        for (noise in listOf(
            "tool_call_start", "tool_call_end", "inference_start",
            "inference_end", "agent_tick_start", "replay_start", "replay_end",
        )) {
            assertThat(alerts.consider(event(noise), "dev_1", "laptop")).isNull()
        }
    }

    @Test
    fun `the same approval does not alert twice`() {
        val alerts = Alerts()

        assertThat(alerts.consider(approvalRequested(), "dev_1", "laptop")).isNotNull()
        // Reconnecting replays what was missed, so this arrives again on every
        // network change. Buzzing the phone each time is how a useful alert
        // becomes one people turn off.
        assertThat(alerts.consider(approvalRequested(), "dev_1", "laptop")).isNull()
    }

    @Test
    fun `different approvals both alert`() {
        val alerts = Alerts()

        assertThat(alerts.consider(approvalRequested("act_1"), "dev_1", "l")).isNotNull()
        assertThat(alerts.consider(approvalRequested("act_2"), "dev_1", "l")).isNotNull()
    }

    @Test
    fun `the same approval id on two desktops is two alerts`() {
        val alerts = Alerts()

        // Ids are per-machine, so two desktops can mint the same one for
        // entirely different questions.
        assertThat(alerts.consider(approvalRequested(), "dev_1", "laptop")).isNotNull()
        assertThat(alerts.consider(approvalRequested(), "dev_2", "studio")).isNotNull()
    }

    @Test
    fun `an approval with no id is not shown`() {
        // There would be nothing to answer: the action id is what a decision
        // is posted against.
        val alert = Alerts().consider(
            event("approval_requested", "tool" to "Bash"), "dev_1", "laptop",
        )

        assertThat(alert).isNull()
    }

    @Test
    fun `an approval with no description still says something`() {
        val alert = Alerts().consider(
            event("approval_requested", "id" to "act_1", "tool" to "Bash"),
            "dev_1",
            "laptop",
        )

        // A blank notification is a question nobody can answer.
        assertThat((alert as Alert.NeedsApproval).summary).isNotEmpty()
    }

    @Test
    fun `a decision elsewhere takes the notification down`() {
        val alerts = Alerts()
        val alert = alerts.consider(approvalRequested(), "dev_1", "laptop")!!

        val cancels = alerts.resolves(
            event("approval_decided", "id" to "act_1", "outcome" to "approved"),
            "dev_1",
        )

        // The answer may have come from the desktop, or from another phone.
        // Leaving it up invites a tap on a question already settled, which
        // fails with a stale-id error that looks like a broken app.
        assertThat(cancels).isEqualTo(alert.key)
    }

    @Test
    fun `a decision on another desktop does not cancel this one`() {
        val alerts = Alerts()
        val alert = alerts.consider(approvalRequested(), "dev_1", "laptop")!!

        val cancels = alerts.resolves(
            event("approval_decided", "id" to "act_1"), "dev_2",
        )

        assertThat(cancels).isNotEqualTo(alert.key)
    }

    @Test
    fun `other events cancel nothing`() {
        val alerts = Alerts()

        assertThat(alerts.resolves(event("tool_call_end"), "dev_1")).isNull()
        assertThat(alerts.resolves(approvalRequested(), "dev_1")).isNull()
    }

    @Test
    fun `clearing a key lets a genuinely new instance alert again`() {
        val alerts = Alerts()
        val alert = alerts.consider(approvalRequested(), "dev_1", "laptop")!!
        assertThat(alerts.consider(approvalRequested(), "dev_1", "laptop")).isNull()

        alerts.clear(alert.key)

        assertThat(alerts.consider(approvalRequested(), "dev_1", "laptop")).isNotNull()
    }
}
