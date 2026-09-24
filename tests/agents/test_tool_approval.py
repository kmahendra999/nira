"""A person gets to say no, and everything that is not a yes is a no.

The approval queue, its endpoints, its permission memory and the ``approve``
scope on a paired device all existed with nothing to put in them: the SDK was
given no ``canUseTool``, so an "ask" was terminal and a risky step was refused
without anyone being offered the choice. These tests cover the piece in
between, and in particular every way it can go wrong — because the failure mode
of getting this backwards is running a destructive command nobody sanctioned.
"""

from __future__ import annotations

import threading
import time

import pytest

from nira.agents.tool_approval import (
    ApprovalBridge,
    PermissionRequest,
    encode_decision,
    permission_key_for,
)
from nira.core.events import EventType
from nira.tools.approval_store import (
    STATUS_APPROVED,
    STATUS_DENIED,
    ApprovalStore,
)


@pytest.fixture
def store(tmp_path):
    approvals = ApprovalStore(str(tmp_path / "approvals.db"))
    yield approvals

    # Let the bridge's workers finish before the connection goes.
    #
    # `handle()` resolves each request on a daemon thread that polls the store
    # for up to its timeout, and the store is one `sqlite3` connection opened
    # with `check_same_thread=False`. Closing it out from under a thread that
    # is mid-query is a use-after-close on the connection object, and it does
    # not raise -- it took the whole xdist worker down, and the failure was
    # reported against whichever test that worker happened to be running.
    #
    # `ApprovalBridge.join` exists for exactly this and no test called it.
    # Doing it here covers every test in the file rather than relying on each
    # one to remember.
    deadline = time.monotonic() + 10.0
    for thread in threading.enumerate():
        if not thread.name.startswith("nira-approval-"):
            continue
        thread.join(max(0.0, deadline - time.monotonic()))
        assert not thread.is_alive(), f"{thread.name} outlived its test"

    approvals.close()


class Sent:
    """Collects the decision lines written back to the sidecar."""

    def __init__(self) -> None:
        self.payloads: list[dict] = []
        self.arrived = threading.Event()

    def __call__(self, payload: dict) -> None:
        self.payloads.append(payload)
        self.arrived.set()

    def wait(self, timeout: float = 5.0) -> dict:
        assert self.arrived.wait(timeout), "no decision was ever sent"
        return self.payloads[-1]


class RecordingBus:
    def __init__(self) -> None:
        self.events: list[tuple] = []
        self._arrived = threading.Condition()

    def publish(self, event_type, data) -> None:  # noqa: ANN001
        with self._arrived:
            self.events.append((event_type, data))
            self._arrived.notify_all()

    def types(self) -> list:
        return [event for event, _ in self.events]

    def await_type(self, event_type, timeout: float = 5.0):  # noqa: ANN001, ANN202
        """Block until *event_type* is published, and return its payload.

        The bridge queues the action into the store and publishes afterwards,
        so waiting for the store to fill -- which is what `_await_queued` does
        -- can return in the gap between the two. Sampling `bus.types()` at
        that moment sees an empty list, which is a race the suite lost on CI
        while passing locally.
        """
        with self._arrived:
            found = self._arrived.wait_for(
                lambda: any(t == event_type for t, _ in self.events),
                timeout=timeout,
            )
        assert found, f"{event_type} was never published"
        return next(d for t, d in self.events if t == event_type)


def request(**overrides) -> dict:
    base = {
        "id": "perm_1",
        "tool": "Bash",
        "input": {"command": "rm -rf build"},
        "title": "Claude wants to run rm -rf build",
    }
    base.update(overrides)
    return base


def bridge_for(store, sent, **kwargs) -> ApprovalBridge:
    return ApprovalBridge(
        store=store,
        send=sent,
        timeout_seconds=kwargs.pop("timeout_seconds", 3.0),
        poll_seconds=0.02,
        **kwargs,
    )


class TestPermissionKey:
    def test_a_shell_command_is_keyed_by_its_verb(self) -> None:
        # Coarse on purpose. Keying on the full command means a remembered
        # "always allow" never matches twice and the memory is decorative.
        assert permission_key_for("Bash", {"command": "git status"}) == "tool:Bash:git"
        assert permission_key_for("Bash", {"command": "git log -5"}) == "tool:Bash:git"

    def test_different_commands_are_different_permissions(self) -> None:
        # ...but not so coarse that approving `ls` authorises `rm`.
        assert permission_key_for("Bash", {"command": "ls"}) != permission_key_for(
            "Bash", {"command": "rm -rf /"}
        )

    def test_other_tools_are_keyed_by_name(self) -> None:
        assert permission_key_for("Read", {"file_path": "/etc/passwd"}) == "tool:Read"

    def test_a_missing_tool_name_still_produces_a_key(self) -> None:
        # A key of "" would collide with every other keyless request, so one
        # remembered decision would answer for all of them.
        assert permission_key_for("", {}) == "tool:unknown"
        assert permission_key_for("Bash", {}) == "tool:Bash"


class TestSummary:
    def test_it_prefers_the_sentence_the_sdk_rendered(self) -> None:
        summary = PermissionRequest.from_event(request()).summary()
        assert summary == "Claude wants to run rm -rf build"

    def test_it_falls_back_to_the_command(self) -> None:
        summary = PermissionRequest.from_event(request(title="")).summary()
        assert "rm -rf build" in summary

    def test_it_never_returns_nothing(self) -> None:
        # An empty line in the queue is a question a person cannot answer.
        summary = PermissionRequest.from_event({"id": "x", "tool": ""}).summary()
        assert summary.strip()


class TestDecisions:
    def test_an_approval_lets_the_tool_run(self, store) -> None:
        sent = Sent()
        bridge = bridge_for(store, sent)
        bridge.handle(request())

        action = _await_queued(store)
        store.update_status(action.id, STATUS_APPROVED)

        assert sent.wait() == {"type": "decision", "id": "perm_1", "behavior": "allow"}

    def test_a_denial_stops_it_and_says_so(self, store) -> None:
        sent = Sent()
        bridge = bridge_for(store, sent)
        bridge.handle(request())

        action = _await_queued(store)
        store.update_status(action.id, STATUS_DENIED)

        decision = sent.wait()
        assert decision["behavior"] == "deny"
        # The SDK surfaces this message to the model, so it has to read as a
        # refusal rather than as a tool failure to be retried.
        assert decision["message"]

    def test_nobody_answering_denies(self, store) -> None:
        sent = Sent()
        bridge = bridge_for(store, sent, timeout_seconds=1.0)
        bridge.handle(request())

        decision = sent.wait(timeout=6.0)
        assert decision["behavior"] == "deny"

    def test_a_timed_out_question_leaves_the_queue(self, store) -> None:
        sent = Sent()
        bridge = bridge_for(store, sent, timeout_seconds=1.0)
        bridge.handle(request())
        sent.wait(timeout=6.0)

        # Otherwise the queue keeps offering a question whose run moved on
        # without it, and answering does nothing.
        assert store.list_pending() == []

    def test_no_store_denies_rather_than_allowing(self) -> None:
        sent = Sent()
        bridge = ApprovalBridge(store=None, send=sent, timeout_seconds=1.0)
        bridge.handle(request())

        decision = sent.wait()
        assert decision["behavior"] == "deny"
        assert "queue" in decision["message"].lower()

    def test_a_broken_store_denies(self, store) -> None:
        class Exploding:
            def get_permission(self, key):  # noqa: ANN001, ANN202
                raise RuntimeError("database is locked")

        sent = Sent()
        bridge = ApprovalBridge(store=Exploding(), send=sent, timeout_seconds=1.0)
        bridge.handle(request())

        # The failure mode of the opposite choice is running a destructive
        # command because SQLite was busy.
        assert sent.wait()["behavior"] == "deny"

    def test_a_request_with_no_id_is_dropped(self, store) -> None:
        sent = Sent()
        bridge = bridge_for(store, sent)
        bridge.handle({"tool": "Bash", "input": {}})
        time.sleep(0.2)

        # Nothing to reply to: a decision keyed on "" would resolve whichever
        # pending request happened to share it.
        assert sent.payloads == []
        assert store.list_pending() == []


class TestRememberedDecisions:
    def test_an_always_approve_answers_without_asking(self, store) -> None:
        store.set_permission("tool:Bash:git", "always_approve")
        sent = Sent()
        bridge = bridge_for(store, sent)
        bridge.handle(request(input={"command": "git status"}))

        assert sent.wait()["behavior"] == "allow"
        # Nothing was queued, so nobody was interrupted.
        assert store.list_pending() == []

    def test_an_always_deny_answers_without_asking(self, store) -> None:
        store.set_permission("tool:Bash:rm", "always_deny")
        sent = Sent()
        bridge = bridge_for(store, sent)
        bridge.handle(request(input={"command": "rm -rf /"}))

        assert sent.wait()["behavior"] == "deny"
        assert store.list_pending() == []

    def test_memory_for_one_command_does_not_cover_another(self, store) -> None:
        store.set_permission("tool:Bash:ls", "always_approve")
        sent = Sent()
        bridge = bridge_for(store, sent, timeout_seconds=1.0)
        bridge.handle(request(input={"command": "rm -rf /"}))

        # The whole point of keying on the verb.
        assert sent.wait(timeout=6.0)["behavior"] == "deny"


class TestQueuedAction:
    def test_the_queued_row_describes_what_is_being_asked(self, store) -> None:
        sent = Sent()
        bridge = bridge_for(store, sent)
        bridge.handle(request())
        action = _await_queued(store)

        assert action.description == "Claude wants to run rm -rf build"
        assert action.payload["tool"] == "Bash"
        assert action.payload["input"]["command"] == "rm -rf build"

    def test_world_changing_tools_are_never_auto_remembered(self, store) -> None:
        sent = Sent()
        bridge = bridge_for(store, sent)
        bridge.handle(request(tool="Write", input={"file_path": "/etc/hosts"}))
        action = _await_queued(store)

        # TIER_HIGH means "always ask" — one yes to writing a file must not
        # silently authorise every future write.
        assert action.tier == "high"

    def test_reading_is_not_treated_as_destructive(self, store) -> None:
        sent = Sent()
        bridge = bridge_for(store, sent)
        bridge.handle(request(tool="Read", input={"file_path": "README.md"}))
        action = _await_queued(store)

        assert action.tier == "medium"


class TestEvents:
    def test_a_waiting_run_announces_itself(self, store) -> None:
        bus = RecordingBus()
        sent = Sent()
        bridge = bridge_for(store, sent, bus=bus, agent_id="claude_code")
        bridge.handle(request())
        action = _await_queued(store)

        # A run parked on a prompt is indistinguishable from a stalled one
        # unless the question reaches the client.
        asked = bus.await_type(EventType.APPROVAL_REQUESTED)
        assert asked["id"] == action.id
        assert asked["tool"] == "Bash"

        store.update_status(action.id, STATUS_APPROVED)
        sent.wait()
        bus.await_type(EventType.APPROVAL_DECIDED)

    def test_a_remembered_answer_still_announces_the_outcome(self, store) -> None:
        store.set_permission("tool:Bash:git", "always_approve")
        bus = RecordingBus()
        sent = Sent()
        bridge = bridge_for(store, sent, bus=bus)
        bridge.handle(request(input={"command": "git status"}))
        sent.wait()

        decided = bus.await_type(EventType.APPROVAL_DECIDED)
        # Otherwise an auto-approved step looks like it was never checked.
        assert decided["remembered"] is True
        assert decided["outcome"] == "approved"

    def test_a_failing_bus_does_not_change_the_decision(self, store) -> None:
        class Exploding:
            def publish(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
                raise RuntimeError("bus is down")

        sent = Sent()
        bridge = bridge_for(store, sent, bus=Exploding())
        bridge.handle(request())
        action = _await_queued(store)
        store.update_status(action.id, STATUS_APPROVED)

        assert sent.wait()["behavior"] == "allow"


class TestWireFormat:
    def test_a_decision_is_one_line(self) -> None:
        # The sidecar reads stdin a line at a time; an embedded newline would
        # split one decision into two unparseable halves.
        line = encode_decision(
            {"type": "decision", "id": "perm_1", "behavior": "allow"}
        )
        assert line.endswith("\n")
        assert line.count("\n") == 1

    def test_a_message_with_newlines_survives(self) -> None:
        line = encode_decision({"type": "decision", "message": "no\nway"})
        assert line.count("\n") == 1


def _await_queued(store: ApprovalStore, timeout: float = 5.0):  # noqa: ANN202
    """Wait for the bridge's worker thread to queue its question."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pending = store.list_pending()
        if pending:
            return pending[0]
        time.sleep(0.02)
    raise AssertionError("nothing was queued for approval")


class TestTheLoopCloses:
    """Set "always allow" from a client, and nobody is asked again.

    The route writing a row and the bridge reading one are each covered
    elsewhere. Neither proves the feature works, because for the whole time
    the store supported `always_approve` and the bridge honoured it, no
    client could set it -- so the two halves had never met.
    """

    def test_remembering_from_the_api_stops_the_next_prompt(
        self, store, monkeypatch
    ) -> None:
        pytest.importorskip("fastapi")
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import nira.server.approval_routes as routes

        monkeypatch.setattr(routes, "_store", store)
        app = FastAPI()
        app.include_router(routes.router)
        client = TestClient(app)

        # A read, not a shell command: `Bash` is in _DESTRUCTIVE and so is
        # always tier high, which is exactly the case that must never be
        # remembered. Reading something is the case that may be.
        sent = Sent()
        bridge = bridge_for(store, sent)
        bridge.handle(request(tool="Read", input={"file_path": "/etc/hosts"}))
        action = _await_queued(store)
        assert action.tier != "high"

        body = client.post(
            f"/v1/approvals/{action.id}/approve", json={"remember": True}
        ).json()
        assert body["remembered"] is True
        assert sent.wait()["behavior"] == "allow"

        # Second time: no question reaches the queue at all.
        again = Sent()
        bridge_for(store, again).handle(
            request(id="perm_2", tool="Read", input={"file_path": "/etc/passwd"})
        )

        assert again.wait()["behavior"] == "allow"
        assert store.list_pending() == [], "nobody should have been asked twice"

    def test_a_destructive_tool_is_asked_every_time(self, store, monkeypatch) -> None:
        """`rm` is tier high, so the API refuses to remember it."""
        pytest.importorskip("fastapi")
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import nira.server.approval_routes as routes

        monkeypatch.setattr(routes, "_store", store)
        app = FastAPI()
        app.include_router(routes.router)
        client = TestClient(app)

        sent = Sent()
        bridge_for(store, sent).handle(request())
        action = _await_queued(store)

        body = client.post(
            f"/v1/approvals/{action.id}/approve", json={"remember": True}
        ).json()
        assert body["remembered"] is False
        sent.wait()

        again = Sent()
        bridge_for(store, again).handle(request(id="perm_2"))

        # Asked again, rather than silently allowed from a remembered yes.
        assert _await_queued(store).permission_key == "tool:Bash:rm"
        store.update_status(store.list_pending()[0].id, STATUS_APPROVED)
        again.wait()
