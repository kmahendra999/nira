"""Device enrolment over HTTP.

`nira device pair` mints an invitation and shows it as a QR. Without these
routes that QR pointed nowhere: pairing could only be completed by running
Python on the desktop, which defeats the purpose of putting a code on screen.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="nira[server] not installed")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nira.devices import DeviceStore
from nira.server.auth_middleware import AuthMiddleware
from nira.server.device_routes import devices_router


@pytest.fixture
def store(tmp_path):
    registry = DeviceStore(tmp_path / "devices.db")
    yield registry
    registry.close()


@pytest.fixture
def client(store):
    app = FastAPI()
    app.state.device_store = store
    app.add_middleware(AuthMiddleware, api_key="nira_sk_machine", device_store=store)
    app.include_router(devices_router)
    return TestClient(app)


class TestEnrolment:
    def test_a_fresh_device_can_enrol_without_a_key(self, client, store) -> None:
        """The whole point: a device that has not paired has nothing to
        present, and the invitation itself is the credential."""
        token = store.create_enrollment("Pixel 8").token

        resp = client.post(
            "/v1/devices/enroll", json={"token": token, "platform": "android"}
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "Pixel 8"
        assert body["key"].startswith("nira_dk_")
        assert body["scopes"] == ["ask", "watch"]

    def test_the_issued_key_authenticates(self, client, store) -> None:
        token = store.create_enrollment("Pixel 8").token
        key = client.post("/v1/devices/enroll", json={"token": token}).json()["key"]

        resp = client.get("/v1/devices/me", headers={"Authorization": f"Bearer {key}"})

        assert resp.status_code == 200
        assert resp.json()["device"]["name"] == "Pixel 8"

    def test_a_token_cannot_be_redeemed_twice(self, client, store) -> None:
        token = store.create_enrollment("Pixel 8").token
        client.post("/v1/devices/enroll", json={"token": token})

        assert (
            client.post("/v1/devices/enroll", json={"token": token}).status_code == 403
        )

    def test_an_unknown_token_is_refused(self, client) -> None:
        resp = client.post("/v1/devices/enroll", json={"token": "nira_en_nope"})

        assert resp.status_code == 403

    def test_failures_are_indistinguishable(self, client, store) -> None:
        """Unknown, used and expired must read the same.

        Telling them apart tells an attacker which tokens ever existed.
        """
        used = store.create_enrollment("A").token
        client.post("/v1/devices/enroll", json={"token": used})

        unknown = client.post("/v1/devices/enroll", json={"token": "nira_en_nope"})
        replayed = client.post("/v1/devices/enroll", json={"token": used})

        assert unknown.status_code == replayed.status_code
        assert unknown.json()["detail"] == replayed.json()["detail"]

    def test_a_missing_token_is_a_bad_request(self, client) -> None:
        assert client.post("/v1/devices/enroll", json={}).status_code == 400

    def test_a_non_json_body_is_a_bad_request(self, client) -> None:
        resp = client.post(
            "/v1/devices/enroll",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )

        assert resp.status_code == 400

    def test_an_overlong_platform_is_truncated_not_rejected(
        self, client, store
    ) -> None:
        """It is a display label, so cap it rather than failing the pairing."""
        token = store.create_enrollment("Phone").token

        resp = client.post(
            "/v1/devices/enroll", json={"token": token, "platform": "x" * 500}
        )

        assert resp.status_code == 200
        assert len(store.get(resp.json()["device_id"]).platform) <= 32


class TestAuthBoundary:
    def test_only_enroll_is_exempt(self, client) -> None:
        """The exemption is one exact path, not a prefix, so a route added
        under /v1/devices later does not inherit it."""
        assert client.get("/v1/devices/me").status_code == 401

    def test_the_machine_key_is_not_a_device(self, client) -> None:
        resp = client.get(
            "/v1/devices/me", headers={"Authorization": "Bearer nira_sk_machine"}
        )

        assert resp.status_code == 200
        assert resp.json()["device"] is None
        assert resp.json()["scopes"] == ["admin"]

    def test_a_revoked_device_loses_access_immediately(self, client, store) -> None:
        token = store.create_enrollment("Pixel 8").token
        body = client.post("/v1/devices/enroll", json={"token": token}).json()
        headers = {"Authorization": f"Bearer {body['key']}"}
        assert client.get("/v1/devices/me", headers=headers).status_code == 200

        store.revoke(body["device_id"])

        assert client.get("/v1/devices/me", headers=headers).status_code == 401


class TestWithoutARegistry:
    def test_enrolment_reports_unavailable_rather_than_crashing(self) -> None:
        app = FastAPI()
        app.include_router(devices_router)

        resp = TestClient(app).post("/v1/devices/enroll", json={"token": "x"})

        assert resp.status_code == 501
