"""WebSocket authentication tests (issue #217).

The HTTP ``AuthMiddleware`` never sees WebSocket upgrade requests, so the
streaming endpoints (`/v1/chat/stream`, `/v1/agents/events`) must validate the
token themselves in the handshake before accepting the connection.
"""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from nira.core.events import EventBus, EventType  # noqa: E402
from nira.server.api_routes import include_all_routes  # noqa: E402
from nira.server.auth_middleware import websocket_authorized  # noqa: E402
from nira.server.ws_bridge import create_ws_router  # noqa: E402

AUTH_PROTOCOL = "nira.auth.v1"
KEY_PROTOCOL_PREFIX = "nira.key.b64url."


def _auth_subprotocols(api_key: str) -> list[str]:
    encoded = base64.urlsafe_b64encode(api_key.encode()).decode().rstrip("=")
    return [AUTH_PROTOCOL, f"{KEY_PROTOCOL_PREFIX}{encoded}"]


def _ws(query=None, headers=None, subprotocols=None):
    stub = MagicMock()
    stub.query_params = query or {}
    stub.headers = headers or {}
    stub.scope = {"subprotocols": subprotocols or []}
    return stub


class TestWebsocketAuthorizedHelper:
    def test_no_key_allows_all(self):
        assert websocket_authorized(_ws(), "") is True

    def test_token_via_bearer_header(self):
        ws = _ws(headers={"authorization": "Bearer sek"})
        assert websocket_authorized(ws, "sek") is True

    @pytest.mark.parametrize(
        "api_key,credential_protocol",
        [
            ("secret+/=", "nira.key.b64url.c2VjcmV0Ky89"),
            ("bearer", "nira.key.b64url.YmVhcmVy"),
            ("sëcret🔑", "nira.key.b64url.c8OrY3JldPCflJE"),
        ],
    )
    def test_token_via_subprotocol(self, api_key, credential_protocol):
        ws = _ws(subprotocols=[AUTH_PROTOCOL, credential_protocol])
        assert websocket_authorized(ws, api_key) is True

    def test_valid_subprotocol_survives_conflicting_authorization(self):
        ws = _ws(
            headers={"authorization": "Bearer proxy-token"},
            subprotocols=_auth_subprotocols("secret+/="),
        )
        assert websocket_authorized(ws, "secret+/=") is True

    def test_valid_authorization_survives_conflicting_subprotocol(self):
        ws = _ws(
            headers={"authorization": "Bearer secret"},
            subprotocols=_auth_subprotocols("wrong"),
        )
        assert websocket_authorized(ws, "secret") is True

    def test_query_token_no_longer_accepted(self):
        # A ?token= query param would leak the key into server access logs;
        # only headers and Sec-WebSocket-Protocol are honored.
        assert websocket_authorized(_ws(query={"token": "sek"}), "sek") is False

    def test_wrong_token_rejected(self):
        ws = _ws(subprotocols=_auth_subprotocols("nope"))
        assert websocket_authorized(ws, "sek") is False

    @pytest.mark.parametrize(
        "subprotocols",
        [
            [AUTH_PROTOCOL],
            [AUTH_PROTOCOL, KEY_PROTOCOL_PREFIX],
            [AUTH_PROTOCOL, AUTH_PROTOCOL],
            [AUTH_PROTOCOL, f"{KEY_PROTOCOL_PREFIX}c2Vr", "extra"],
            ["bearer", "sek"],
        ],
    )
    def test_malformed_subprotocol_offer_rejected(self, subprotocols):
        assert websocket_authorized(_ws(subprotocols=subprotocols), "sek") is False

    def test_missing_token_rejected_when_required(self):
        assert websocket_authorized(_ws(), "sek") is False


def _make_app(api_key=""):
    app = FastAPI()
    engine = MagicMock()
    engine.engine_id = "mock"

    async def mock_stream(messages, *, model="test-model", **kwargs):
        for tok in ["hi"]:
            yield tok

    engine.stream = mock_stream
    app.state.engine = engine
    app.state.model = "test-model"
    app.state.api_key = api_key
    include_all_routes(app)
    return app


class TestChatStreamAuth:
    def test_rejected_without_token_when_key_set(self):
        client = TestClient(_make_app(api_key="secret"))
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/v1/chat/stream") as ws:
                ws.receive_text()

    def test_rejected_with_wrong_token(self):
        client = TestClient(_make_app(api_key="secret"))
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/v1/chat/stream", subprotocols=_auth_subprotocols("wrong")
            ) as ws:
                ws.receive_text()

    def test_rejected_with_query_token(self):
        # ?token= is no longer an accepted auth channel (would leak into logs).
        client = TestClient(_make_app(api_key="secret"))
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/v1/chat/stream?token=secret") as ws:
                ws.receive_text()

    def test_accepted_with_correct_token(self):
        api_key = "secret+/="
        client = TestClient(_make_app(api_key=api_key))
        with client.websocket_connect(
            "/v1/chat/stream", subprotocols=_auth_subprotocols(api_key)
        ) as ws:
            assert ws.accepted_subprotocol == AUTH_PROTOCOL
            ws.send_text(json.dumps({"message": "hi"}))
            assert ws.receive_json()["type"] in ("chunk", "done", "error")

    def test_accepted_with_authorization_header(self):
        client = TestClient(_make_app(api_key="secret"))
        with client.websocket_connect(
            "/v1/chat/stream", headers={"Authorization": "Bearer secret"}
        ) as ws:
            assert ws.accepted_subprotocol is None
            ws.send_text(json.dumps({"message": "hi"}))
            assert ws.receive_json()["type"] in ("chunk", "done", "error")

    def test_allowed_when_no_key_configured(self):
        client = TestClient(_make_app(api_key=""))
        with client.websocket_connect("/v1/chat/stream") as ws:
            ws.send_text(json.dumps({"message": "hi"}))
            assert ws.receive_json()["type"] in ("chunk", "done", "error")

    def test_keyless_server_negotiates_stale_client_auth_protocol(self):
        client = TestClient(_make_app(api_key=""))
        with client.websocket_connect(
            "/v1/chat/stream", subprotocols=_auth_subprotocols("stale")
        ) as ws:
            assert ws.accepted_subprotocol == AUTH_PROTOCOL
            ws.send_text(json.dumps({"message": "hi"}))
            assert ws.receive_json()["type"] in ("chunk", "done", "error")


class TestAgentEventsAuth:
    def _app(self, api_key=""):
        app = FastAPI()
        app.state.api_key = api_key
        app.include_router(create_ws_router(EventBus()))
        return app

    def test_rejected_without_token_when_key_set(self):
        client = TestClient(self._app(api_key="secret"))
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/v1/agents/events") as ws:
                ws.receive_text()

    def test_rejected_with_query_token(self):
        client = TestClient(self._app(api_key="secret"))
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/v1/agents/events?token=secret") as ws:
                ws.receive_text()

    def test_accepted_with_correct_token(self):
        bus = EventBus()
        app = FastAPI()
        api_key = "secret+/="
        app.state.api_key = api_key
        app.include_router(create_ws_router(bus))
        client = TestClient(app)
        with client.websocket_connect(
            "/v1/agents/events", subprotocols=_auth_subprotocols(api_key)
        ) as ws:
            assert ws.accepted_subprotocol == AUTH_PROTOCOL
            bus.publish(EventType.AGENT_TICK_START, {"agent_id": "a"})
            assert ws.receive_json()["data"]["agent_id"] == "a"

    def test_accepted_with_authorization_header(self):
        bus = EventBus()
        app = FastAPI()
        app.state.api_key = "secret"
        app.include_router(create_ws_router(bus))
        client = TestClient(app)
        with client.websocket_connect(
            "/v1/agents/events", headers={"Authorization": "Bearer secret"}
        ) as ws:
            assert ws.accepted_subprotocol is None
            bus.publish(EventType.AGENT_TICK_START, {"agent_id": "a"})
            assert ws.receive_json()["data"]["agent_id"] == "a"


class TestDeviceKeyOverWebsocket:
    """A paired phone must be able to watch the desktop work.

    Until the device store was wired in here, ``authenticate_websocket`` knew
    only the machine key. A phone could send a prompt over HTTP and then be
    refused the events socket that reports progress on it — the live progress
    the whole pairing exists to deliver was the one thing a device key could
    not reach.
    """

    @pytest.fixture
    def store(self, tmp_path):
        from nira.devices.store import DeviceStore

        return DeviceStore(tmp_path / "devices.db")

    @staticmethod
    def _enrol(store, name, scopes):
        enrollment = store.create_enrollment(name, scopes=scopes)
        _device, key = store.redeem_enrollment(enrollment.token, platform="android")
        return key

    def test_device_key_is_accepted_in_a_subprotocol(self, store):
        from nira.server.auth_middleware import authenticate_websocket

        key = self._enrol(store, "phone", ["ask", "watch"])
        ok, protocol = authenticate_websocket(
            _ws(subprotocols=_auth_subprotocols(key)),
            "nira_sk_machine",
            device_store=store,
            required_scope_name="watch",
        )
        assert ok is True
        assert protocol == AUTH_PROTOCOL

    def test_device_key_is_accepted_in_a_bearer_header(self, store):
        from nira.server.auth_middleware import authenticate_websocket

        key = self._enrol(store, "phone", ["watch"])
        ok, _ = authenticate_websocket(
            _ws(headers={"authorization": f"Bearer {key}"}),
            "nira_sk_machine",
            device_store=store,
            required_scope_name="watch",
        )
        assert ok is True

    def test_a_device_without_the_scope_is_refused(self, store):
        from nira.server.auth_middleware import authenticate_websocket

        key = self._enrol(store, "phone", ["ask"])
        ok, _ = authenticate_websocket(
            _ws(subprotocols=_auth_subprotocols(key)),
            "nira_sk_machine",
            device_store=store,
            required_scope_name="watch",
        )
        assert ok is False

    def test_admin_implies_the_scope(self, store):
        from nira.server.auth_middleware import authenticate_websocket

        key = self._enrol(store, "laptop", ["admin"])
        ok, _ = authenticate_websocket(
            _ws(subprotocols=_auth_subprotocols(key)),
            "nira_sk_machine",
            device_store=store,
            required_scope_name="watch",
        )
        assert ok is True

    def test_a_revoked_device_is_refused(self, store):
        from nira.server.auth_middleware import authenticate_websocket

        key = self._enrol(store, "lost-phone", ["admin"])
        store.revoke(store.list()[0].id)
        ok, _ = authenticate_websocket(
            _ws(subprotocols=_auth_subprotocols(key)),
            "nira_sk_machine",
            device_store=store,
            required_scope_name="watch",
        )
        assert ok is False

    def test_an_unknown_key_is_still_refused(self, store):
        from nira.server.auth_middleware import authenticate_websocket

        ok, _ = authenticate_websocket(
            _ws(subprotocols=_auth_subprotocols("nira_dk_never_issued")),
            "nira_sk_machine",
            device_store=store,
            required_scope_name="watch",
        )
        assert ok is False

    def test_without_a_device_store_only_the_machine_key_works(self, store):
        from nira.server.auth_middleware import authenticate_websocket

        key = self._enrol(store, "phone", ["admin"])
        ok, _ = authenticate_websocket(
            _ws(subprotocols=_auth_subprotocols(key)),
            "nira_sk_machine",
            device_store=None,
        )
        assert ok is False

    def test_the_machine_key_never_consults_the_device_store(self, store):
        from nira.server.auth_middleware import authenticate_websocket

        exploding = MagicMock()
        exploding.authenticate.side_effect = AssertionError("must not be reached")
        ok, _ = authenticate_websocket(
            _ws(subprotocols=_auth_subprotocols("nira_sk_machine")),
            "nira_sk_machine",
            device_store=exploding,
            required_scope_name="watch",
        )
        assert ok is True

    def test_a_padded_encoding_still_decodes(self, store):
        """The encoder strips base64 padding; the decoder must put it back."""
        from nira.server.auth_middleware import authenticate_websocket

        # Try several name lengths so at least one key lands on each of the
        # three padding cases.
        for index in range(4):
            key = self._enrol(store, f"phone-{'x' * index}", ["watch"])
            ok, _ = authenticate_websocket(
                _ws(subprotocols=_auth_subprotocols(key)),
                "nira_sk_machine",
                device_store=store,
                required_scope_name="watch",
            )
            assert ok is True, f"padding case {index}"

    def test_a_malformed_credential_does_not_raise(self, store):
        from nira.server.auth_middleware import authenticate_websocket

        ok, _ = authenticate_websocket(
            _ws(subprotocols=[AUTH_PROTOCOL, f"{KEY_PROTOCOL_PREFIX}!!!not-base64!!!"]),
            "nira_sk_machine",
            device_store=store,
            required_scope_name="watch",
        )
        assert ok is False
