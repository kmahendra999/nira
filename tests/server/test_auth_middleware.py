"""Tests for API key authentication middleware."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="nira[server] not installed")

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from nira.server.auth_middleware import AuthMiddleware


def _make_app(api_key: str) -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthMiddleware, api_key=api_key)

    @app.get("/v1/models")
    async def models():
        return {"models": []}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/webhooks/twilio")
    async def twilio_webhook():
        return {"status": "received"}

    @app.get("/metrics")
    async def metrics():
        return {"requests": 0}

    return app


@pytest.fixture
def client():
    return TestClient(_make_app("oj_sk_test123"))


class TestAuthMiddleware:
    def test_rejects_missing_auth_header(self, client):
        resp = client.get("/v1/models")
        assert resp.status_code == 401
        assert "missing" in resp.json()["detail"].lower()

    def test_rejects_wrong_key(self, client):
        resp = client.get(
            "/v1/models",
            headers={"Authorization": "Bearer wrong"},
        )
        assert resp.status_code == 401
        assert "invalid" in resp.json()["detail"].lower()

    def test_accepts_valid_key(self, client):
        resp = client.get(
            "/v1/models",
            headers={"Authorization": "Bearer oj_sk_test123"},
        )
        assert resp.status_code == 200

    def test_health_exempt(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_webhooks_exempt(self, client):
        resp = client.post("/webhooks/twilio")
        assert resp.status_code == 200

    def test_metrics_requires_auth(self, client):
        resp = client.get("/metrics")
        assert resp.status_code == 401

    def test_metrics_accepts_valid_key(self, client):
        resp = client.get("/metrics", headers={"Authorization": "Bearer oj_sk_test123"})
        assert resp.status_code == 200

    def test_no_key_configured_allows_all(self):
        client = TestClient(_make_app(""))
        resp = client.get("/v1/models")
        assert resp.status_code == 200
        assert client.get("/metrics").status_code == 200

    def test_cors_preflight_exempt(self, client):
        """Regression for #758: browser preflights never carry Authorization,
        so AuthMiddleware must not reject OPTIONS with 401 -- otherwise the
        request never reaches CORSMiddleware and preflight fails outright."""
        resp = client.options(
            "/v1/models",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code != 401

    @pytest.mark.parametrize(
        "headers",
        [
            {},
            {"Origin": "https://example.com"},
            {"Access-Control-Request-Method": "GET"},
        ],
    )
    def test_non_preflight_options_still_requires_auth(self, client, headers):
        resp = client.options("/v1/models", headers=headers)
        assert resp.status_code == 401


class TestDeviceKeys:
    """A paired device presents its own key, not the machine's.

    One shared token means no way to tell a phone from a laptop, no way to
    revoke one without revoking all, and no per-device audit trail. On a
    tailnet shared with another account, that is not a survivable posture.
    """

    def _app_with_devices(self, tmp_path, api_key="nira_sk_machine"):
        from nira.devices import DeviceStore

        store = DeviceStore(tmp_path / "devices.db")
        app = FastAPI()
        app.add_middleware(AuthMiddleware, api_key=api_key, device_store=store)

        @app.get("/v1/whoami")
        async def whoami(request: Request):
            device = request.scope.get("nira_device")
            return {"device": device.name if device else None}

        return app, store

    def _pair(self, store, name="Pixel 8", scopes=("admin",), **kwargs):
        """Pair a device that can reach the synthetic route below.

        ``admin`` because ``/v1/whoami`` exists only in this test and is
        therefore unclassified — and an unclassified path requires ``admin``
        by design, so that a route added without a thought for phones locks
        down rather than opening up. These tests are about authentication;
        the scope table has its own file.
        """
        enrollment = store.create_enrollment(name, scopes=list(scopes), **kwargs)
        return store.redeem_enrollment(enrollment.token, platform="android")

    def test_a_device_is_held_to_its_scopes(self, tmp_path) -> None:
        app, store = self._app_with_devices(tmp_path)
        try:
            _, key = self._pair(store, scopes=("ask", "watch"))
            resp = TestClient(app).get(
                "/v1/whoami", headers={"Authorization": f"Bearer {key}"}
            )
        finally:
            store.close()

        # Authenticating is not the same as being allowed. A default pairing
        # reaches an unclassified route only to be refused by scope.
        assert resp.status_code == 403
        assert "admin" in resp.json()["detail"]

    def test_a_device_key_is_accepted(self, tmp_path) -> None:
        app, store = self._app_with_devices(tmp_path)
        try:
            _, key = self._pair(store)
            resp = TestClient(app).get(
                "/v1/whoami", headers={"Authorization": f"Bearer {key}"}
            )
        finally:
            store.close()

        assert resp.status_code == 200
        assert resp.json()["device"] == "Pixel 8"

    def test_the_machine_key_still_works(self, tmp_path) -> None:
        app, store = self._app_with_devices(tmp_path)
        try:
            resp = TestClient(app).get(
                "/v1/whoami", headers={"Authorization": "Bearer nira_sk_machine"}
            )
        finally:
            store.close()

        assert resp.status_code == 200
        # No device identity to attach: the machine key is not a device.
        assert resp.json()["device"] is None

    def test_a_key_minted_before_the_rename_still_authenticates(self, tmp_path) -> None:
        """The prefix is cosmetic; comparison is over the whole string."""
        app, store = self._app_with_devices(tmp_path, api_key="oj_sk_legacy")
        try:
            resp = TestClient(app).get(
                "/v1/whoami", headers={"Authorization": "Bearer oj_sk_legacy"}
            )
        finally:
            store.close()

        assert resp.status_code == 200

    def test_a_revoked_device_is_locked_out(self, tmp_path) -> None:
        app, store = self._app_with_devices(tmp_path)
        try:
            device, key = self._pair(store)
            client = TestClient(app)
            assert (
                client.get(
                    "/v1/whoami", headers={"Authorization": f"Bearer {key}"}
                ).status_code
                == 200
            )

            store.revoke(device.id)

            resp = client.get("/v1/whoami", headers={"Authorization": f"Bearer {key}"})
        finally:
            store.close()

        assert resp.status_code == 401

    def test_revoking_one_device_does_not_affect_another(self, tmp_path) -> None:
        """The whole point of per-device keys."""
        app, store = self._app_with_devices(tmp_path)
        try:
            phone, phone_key = self._pair(store, "Phone")
            _, laptop_key = self._pair(store, "Laptop")
            store.revoke(phone.id)

            client = TestClient(app)
            phone_resp = client.get(
                "/v1/whoami", headers={"Authorization": f"Bearer {phone_key}"}
            )
            laptop_resp = client.get(
                "/v1/whoami", headers={"Authorization": f"Bearer {laptop_key}"}
            )
        finally:
            store.close()

        assert phone_resp.status_code == 401
        assert laptop_resp.status_code == 200

    def test_an_unknown_key_is_rejected(self, tmp_path) -> None:
        app, store = self._app_with_devices(tmp_path)
        try:
            resp = TestClient(app).get(
                "/v1/whoami", headers={"Authorization": "Bearer nira_dk_forged"}
            )
        finally:
            store.close()

        assert resp.status_code == 401

    def test_a_client_cannot_spoof_a_device_identity(self, tmp_path) -> None:
        """Identity rides on the ASGI scope, not a header a caller can send."""
        app, store = self._app_with_devices(tmp_path)
        try:
            resp = TestClient(app).get(
                "/v1/whoami",
                headers={
                    "Authorization": "Bearer nira_sk_machine",
                    "X-Nira-Device": "Attacker Phone",
                },
            )
        finally:
            store.close()

        assert resp.json()["device"] is None

    def test_a_registry_fault_does_not_authorise(self, tmp_path) -> None:
        """Failing open here would turn a database error into a bypass."""

        class _BrokenStore:
            def authenticate(self, key):
                raise RuntimeError("database on fire")

        app = FastAPI()
        app.add_middleware(
            AuthMiddleware, api_key="nira_sk_machine", device_store=_BrokenStore()
        )

        @app.get("/v1/ping")
        async def ping():
            return {"ok": True}

        resp = TestClient(app).get(
            "/v1/ping", headers={"Authorization": "Bearer nira_dk_anything"}
        )

        assert resp.status_code == 401

    def test_using_a_device_key_records_that_it_was_seen(self, tmp_path) -> None:
        app, store = self._app_with_devices(tmp_path)
        try:
            device, key = self._pair(store)
            assert store.get(device.id).last_seen_at == ""

            TestClient(app).get(
                "/v1/whoami", headers={"Authorization": f"Bearer {key}"}
            )

            assert store.get(device.id).last_seen_at != ""
        finally:
            store.close()
