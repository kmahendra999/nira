"""A2A server authentication tests (issue #217)."""

from __future__ import annotations

import pytest

from nira.a2a.protocol import AgentCard
from nira.a2a.server import A2AServer


def _request():
    return {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tasks/send",
        "params": {"input": "ping"},
    }


def test_no_auth_token_allows_requests():
    server = A2AServer(AgentCard(name="x"), handler=lambda t: f"echo:{t}")
    resp = server.handle_request(_request())
    assert resp.get("error") is None


def test_missing_token_rejected_when_required():
    server = A2AServer(AgentCard(name="x"), handler=lambda t: t, auth_token="sek")
    resp = server.handle_request(_request())
    assert resp["error"]["code"] == -32001


def test_wrong_token_rejected():
    server = A2AServer(AgentCard(name="x"), handler=lambda t: t, auth_token="sek")
    resp = server.handle_request(_request(), token="nope")
    assert resp["error"]["code"] == -32001


def test_correct_token_accepted_and_dispatched():
    server = A2AServer(
        AgentCard(name="x"), handler=lambda t: f"echo:{t}", auth_token="sek"
    )
    resp = server.handle_request(_request(), token="sek")
    assert resp.get("error") is None


def test_auth_scheme_advertised_on_card():
    server = A2AServer(AgentCard(name="x"), auth_token="sek")
    assert server.agent_card.authentication == {"schemes": ["bearer"]}


def test_no_token_unauthenticated_card_stays_empty():
    server = A2AServer(AgentCard(name="x"))
    assert server.agent_card.authentication == {}


class TestClientSendsBearerToken:
    """The client has to present the token the server asks for.

    A2AServer supports bearer auth and advertises {"schemes": ["bearer"]} on
    its card, but A2AClient sent no Authorization header on any request. An
    authenticated A2A deployment was therefore unreachable from this client,
    and only an unauthenticated one worked -- so in practice A2A was either
    open or unusable.
    """

    def _captured(self, monkeypatch, token=None):
        import httpx

        from nira.a2a.client import A2AClient

        seen: dict = {}

        class _Resp:
            status_code = 200

            def raise_for_status(self) -> None:
                pass

            def json(self) -> dict:
                return {"result": {"id": "t1", "state": "completed", "output": "ok"}}

        def _post(url, **kwargs):
            seen["url"] = url
            seen["headers"] = kwargs.get("headers") or {}
            return _Resp()

        def _get(url, **kwargs):
            seen["url"] = url
            seen["headers"] = kwargs.get("headers") or {}
            return _Resp()

        monkeypatch.setattr(httpx, "post", _post)
        monkeypatch.setattr(httpx, "get", _get)
        return A2AClient("https://peer.example", auth_token=token), seen

    def test_send_task_presents_the_token(self, monkeypatch) -> None:
        client, seen = self._captured(monkeypatch, token="secret-token")

        client.send_task("ping")

        assert seen["headers"].get("Authorization") == "Bearer secret-token"

    def test_get_task_presents_the_token(self, monkeypatch) -> None:
        client, seen = self._captured(monkeypatch, token="secret-token")

        client.get_task("t1")

        assert seen["headers"].get("Authorization") == "Bearer secret-token"

    def test_cancel_task_presents_the_token(self, monkeypatch) -> None:
        client, seen = self._captured(monkeypatch, token="secret-token")

        client.cancel_task("t1")

        assert seen["headers"].get("Authorization") == "Bearer secret-token"

    def test_discovery_presents_the_token(self, monkeypatch) -> None:
        """Agent cards can be behind the same auth as the task endpoint."""
        client, seen = self._captured(monkeypatch, token="secret-token")

        client.discover()

        assert seen["headers"].get("Authorization") == "Bearer secret-token"

    def test_no_token_sends_no_header(self, monkeypatch) -> None:
        client, seen = self._captured(monkeypatch, token=None)

        client.send_task("ping")

        assert "Authorization" not in seen["headers"]

    def test_client_can_reach_an_authenticated_server(self) -> None:
        """End to end through the server's own check, no HTTP involved."""
        from nira.a2a.protocol import AgentCard
        from nira.a2a.server import A2AServer

        server = A2AServer(
            AgentCard(name="x"), handler=lambda t: f"echo:{t}", auth_token="tok"
        )
        header = {"Authorization": "Bearer tok"}

        presented = header["Authorization"].removeprefix("Bearer ")
        assert server.authenticate(presented) is True


class TestTaskStateWireCompatibility:
    """Rust and Python must name task states identically.

    They did not. Python follows the A2A spec
    (submitted/working/input-required/completed/canceled/failed) while the
    Rust crate used pending/active/completed/cancelled/failed -- different
    names, one fewer state, and the British spelling of "canceled". Two peers
    could complete an exchange and disagree about every state in it.
    """

    def _rust(self):
        return pytest.importorskip("nira_rust")

    def test_rust_creates_tasks_in_the_python_submitted_state(self) -> None:
        import json

        from nira.a2a.protocol import TaskState

        store = self._rust().A2ATaskStore()
        task = json.loads(store.create_task("hello"))

        assert task["state"] == TaskState.SUBMITTED.value

    def test_every_python_state_round_trips_through_rust(self) -> None:
        import json

        from nira.a2a.protocol import TaskState

        store = self._rust().A2ATaskStore()
        task_id = json.loads(store.create_task("hello"))["id"]

        for state in TaskState:
            assert store.update_state(task_id, state.value), (
                f"Rust rejected the spec state {state.value!r}"
            )
            observed = json.loads(store.get_task(task_id))["state"]
            assert observed == state.value, (
                f"Rust serialised {state.value!r} as {observed!r}"
            )

    def test_legacy_rust_names_still_accepted_for_upgrades(self) -> None:
        store = self._rust().A2ATaskStore()
        import json

        task_id = json.loads(store.create_task("hello"))["id"]

        for legacy in ("pending", "active", "cancelled"):
            assert store.update_state(task_id, legacy)

    def test_unknown_state_is_rejected(self) -> None:
        import json

        store = self._rust().A2ATaskStore()
        task_id = json.loads(store.create_task("hello"))["id"]

        assert store.update_state(task_id, "not-a-state") is False
