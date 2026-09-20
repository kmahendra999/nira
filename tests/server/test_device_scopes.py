"""A device key must not be the machine key in disguise.

Scopes have been issued since devices existed and attached to every request,
but until now nothing read them: a phone paired with ``ask`` and ``watch``
could rewrite config and revoke other devices. These tests pin down the part
that reads them.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nira.devices.store import DeviceStore
from nira.server.auth_middleware import AuthMiddleware
from nira.server.device_scopes import NO_SCOPE, required_scope

API_KEY = "nira_sk_machine_key_for_tests"


class TestRequiredScope:
    """The classification itself, independent of any server."""

    @pytest.mark.parametrize(
        ("method", "path", "expected"),
        [
            ("POST", "/v1/chat/completions", "ask"),
            ("POST", "/v1/speech/transcribe", "ask"),
            ("GET", "/v1/speech/health", "watch"),
            ("GET", "/v1/info", "watch"),
            ("GET", "/v1/agents", "watch"),
            ("GET", "/v1/sessions/abc", "watch"),
            ("POST", "/v1/approvals/xyz/approve", "approve"),
            ("GET", "/v1/approvals/pending", "approve"),
            ("GET", "/v1/config", "admin"),
            ("POST", "/v1/vault/unlock", "admin"),
            ("GET", "/metrics", "admin"),
        ],
    )
    def test_classifies_known_paths(self, method, path, expected):
        assert required_scope(method, path) == expected

    def test_unknown_paths_require_admin(self):
        # Default-deny. A route added later without a thought for phones gets
        # locked down rather than opened up.
        assert required_scope("GET", "/v1/something-invented-tomorrow") == "admin"
        assert required_scope("POST", "/api/whatever") == "admin"

    def test_writing_to_a_watchable_path_is_asking(self):
        # Reading the agent list is watching; starting an agent is work.
        assert required_scope("GET", "/v1/agents") == "watch"
        assert required_scope("POST", "/v1/agents") == "ask"

    def test_destroying_is_not_asking(self):
        # "ask" buys the ability to make the desktop work, not to delete what
        # is already there. A lost phone should not be able to wipe memories.
        assert required_scope("DELETE", "/v1/memory/abc") == "admin"
        assert required_scope("PUT", "/v1/memory/abc") == "admin"
        assert required_scope("PATCH", "/v1/sessions/abc") == "admin"
        # The explicitly-classified ask paths are unaffected.
        assert required_scope("POST", "/v1/chat/completions") == "ask"

    def test_a_device_can_always_read_its_own_identity(self):
        # /v1/devices is otherwise admin-only, but a device must be able to
        # ask what it was granted whatever that turns out to be — a client
        # decides which controls to show from exactly this answer, so a
        # narrowly-paired phone would otherwise be unable to discover that it
        # is narrowly paired.
        assert required_scope("GET", "/v1/devices/me") == NO_SCOPE
        assert required_scope("GET", "/v1/devices") == "admin"

    def test_trailing_slashes_do_not_change_the_answer(self):
        assert required_scope("GET", "/v1/info/") == "watch"
        assert required_scope("GET", "/v1/config/") == "admin"

    def test_a_prefix_match_is_not_a_substring_match(self):
        # "/v1/configuration-wizard" is not "/v1/config" — but it is also not
        # classified, so it must still land on admin rather than slip through.
        assert required_scope("GET", "/v1/configuration-wizard") == "admin"


@pytest.fixture
def app_and_store(tmp_path):
    """A minimal app with the real middleware and a real device registry."""
    store = DeviceStore(tmp_path / "devices.db")
    app = FastAPI()
    app.add_middleware(AuthMiddleware, api_key=API_KEY, device_store=store)

    @app.get("/v1/info")
    async def info():
        return {"ok": True}

    @app.post("/v1/chat/completions")
    async def chat():
        return {"ok": True}

    @app.get("/v1/config")
    async def config():
        return {"ok": True}

    @app.post("/v1/approvals/abc/approve")
    async def approve():
        return {"ok": True}

    @app.get("/v1/brand-new-route")
    async def unclassified():
        return {"ok": True}

    @app.get("/v1/devices/me")
    async def whoami():
        return {"ok": True}

    return app, store


def _enrol(store: DeviceStore, name: str, scopes: list[str]) -> str:
    enrollment = store.create_enrollment(name, scopes=scopes)
    _device, key = store.redeem_enrollment(enrollment.token, platform="android")
    return key


class TestScopeEnforcement:
    def test_machine_key_is_unaffected(self, app_and_store):
        app, _ = app_and_store
        client = TestClient(app)
        # The desktop UI and CLI use this key and have no device identity;
        # constraining them would break every existing caller.
        for path in ("/v1/info", "/v1/config", "/v1/brand-new-route"):
            response = client.get(path, headers={"Authorization": f"Bearer {API_KEY}"})
            assert response.status_code == 200, path

    def test_default_device_can_ask_and_watch(self, app_and_store):
        app, store = app_and_store
        key = _enrol(store, "phone", ["ask", "watch"])
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {key}"}

        assert client.get("/v1/info", headers=headers).status_code == 200
        assert client.post("/v1/chat/completions", headers=headers).status_code == 200

    def test_default_device_cannot_administer(self, app_and_store):
        app, store = app_and_store
        key = _enrol(store, "phone", ["ask", "watch"])
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {key}"}

        response = client.get("/v1/config", headers=headers)
        assert response.status_code == 403
        # The message has to name the missing scope, or the fix is a guess.
        assert "admin" in response.json()["detail"]

    def test_a_watch_only_device_cannot_send_prompts(self, app_and_store):
        app, store = app_and_store
        key = _enrol(store, "wall-display", ["watch"])
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {key}"}

        assert client.get("/v1/info", headers=headers).status_code == 200
        assert client.post("/v1/chat/completions", headers=headers).status_code == 403

    def test_an_ask_only_device_cannot_approve(self, app_and_store):
        app, store = app_and_store
        key = _enrol(store, "phone", ["ask"])
        client = TestClient(app)

        response = client.post(
            "/v1/approvals/abc/approve", headers={"Authorization": f"Bearer {key}"}
        )
        assert response.status_code == 403

    def test_an_approve_device_can_approve(self, app_and_store):
        app, store = app_and_store
        key = _enrol(store, "phone", ["ask", "watch", "approve"])
        client = TestClient(app)

        response = client.post(
            "/v1/approvals/abc/approve", headers={"Authorization": f"Bearer {key}"}
        )
        assert response.status_code == 200

    def test_admin_scope_opens_everything(self, app_and_store):
        app, store = app_and_store
        key = _enrol(store, "my-laptop", ["admin"])
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {key}"}

        assert client.get("/v1/config", headers=headers).status_code == 200
        assert client.get("/v1/brand-new-route", headers=headers).status_code == 200
        # Admin implies the rest; see Device.can.
        assert client.post("/v1/chat/completions", headers=headers).status_code == 200

    def test_an_unclassified_route_is_closed_to_a_normal_device(self, app_and_store):
        app, store = app_and_store
        key = _enrol(store, "phone", ["ask", "watch"])
        client = TestClient(app)

        response = client.get(
            "/v1/brand-new-route", headers={"Authorization": f"Bearer {key}"}
        )
        assert response.status_code == 403

    def test_a_revoked_device_is_refused_before_scopes_are_consulted(
        self, app_and_store
    ):
        app, store = app_and_store
        key = _enrol(store, "lost-phone", ["admin"])
        device = store.list()[0]
        store.revoke(device.id)
        client = TestClient(app)

        response = client.get("/v1/info", headers={"Authorization": f"Bearer {key}"})
        # 401, not 403: a revoked device is nobody, not somebody lacking a
        # scope. Saying "you need watch" would confirm the key was once real.
        assert response.status_code == 401

    def test_the_narrowest_device_can_still_read_its_own_identity(self, app_and_store):
        app, store = app_and_store
        key = _enrol(store, "phone", ["ask"])
        client = TestClient(app)

        response = client.get(
            "/v1/devices/me", headers={"Authorization": f"Bearer {key}"}
        )
        assert response.status_code == 200

    def test_devices_me_still_needs_a_valid_key(self, app_and_store):
        app, _store = app_and_store
        client = TestClient(app)

        # No scope required is not the same as no authentication required.
        assert client.get("/v1/devices/me").status_code == 401
        assert (
            client.get(
                "/v1/devices/me", headers={"Authorization": "Bearer nira_dk_bogus"}
            ).status_code
            == 401
        )

    def test_denial_does_not_reveal_the_machine_key(self, app_and_store):
        app, store = app_and_store
        key = _enrol(store, "phone", ["ask"])
        client = TestClient(app)

        response = client.get("/v1/config", headers={"Authorization": f"Bearer {key}"})
        assert API_KEY not in response.text


class TestApiPathsAreNotAnsweredByTheWebApp:
    """The SPA catch-all matched every unclaimed GET, including ``/v1``.

    A missing, misspelled or not-yet-written API route returned 200 and a
    kilobyte of ``index.html``. A browser shrugs at that; no other client does.
    The phone parses it as JSON and reports a syntax error, which sends whoever
    is debugging to the client instead of to the absent route — and it hides
    endpoints that were never written at all.
    """

    def test_api_prefixes_are_recognised(self) -> None:
        from nira.server.app import _is_api_path

        for path in ("/v1/devices", "/v1/anything", "/api/digest", "/metrics"):
            assert _is_api_path(path), path

    def test_app_routes_are_not(self) -> None:
        from nira.server.app import _is_api_path

        # These have to keep reaching index.html or the web app stops working
        # on a deep link.
        for path in ("/", "/settings", "/agents", "/assets/index.js", "/favicon.ico"):
            assert not _is_api_path(path), path

    def test_a_path_that_merely_starts_with_the_letters_is_not_an_api_path(
        self,
    ) -> None:
        from nira.server.app import _is_api_path

        # "/v1-changelog" is a page, not an endpoint. Matching on the bare
        # prefix would 404 a legitimate route in the web app.
        assert not _is_api_path("/v1-changelog")
        assert not _is_api_path("/apitest")

    def test_the_bare_prefix_is_an_api_path(self) -> None:
        from nira.server.app import _is_api_path

        assert _is_api_path("/v1")
        assert _is_api_path("/api")
