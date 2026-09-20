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


def _machine() -> dict[str, str]:
    return {"Authorization": "Bearer nira_sk_machine"}


def _bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def _enrol(store: DeviceStore, name: str) -> str:
    """Pair a device and return the key it was issued."""
    enrollment = store.create_enrollment(name)
    _device, key = store.redeem_enrollment(enrollment.token, platform="android")
    return key


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


class TestListingAndRevoking:
    """Seeing and removing devices, from something other than the machine.

    The moment this matters most is the moment you are not at the desktop: a
    phone has been lost, and the revoking has to happen from whatever device
    you still have. Until now the only way was a shell on the machine itself.
    """

    def test_devices_can_be_listed(self, client, store) -> None:
        _enrol(store, "phone-one")
        _enrol(store, "phone-two")

        response = client.get("/v1/devices", headers=_machine())

        assert response.status_code == 200
        names = [d["name"] for d in response.json()["devices"]]
        assert sorted(names) == ["phone-one", "phone-two"]

    def test_a_listing_never_carries_a_key(self, client, store) -> None:
        key = _enrol(store, "phone-one")

        body = client.get("/v1/devices", headers=_machine()).text

        # Only a hash is stored, but a regression that started returning the
        # key would hand every device every other device's credential.
        assert key not in body

    def test_revoked_devices_are_hidden_by_default(self, client, store) -> None:
        _enrol(store, "phone-one")
        device_id = store.list()[0].id
        store.revoke(device_id)

        listed = client.get("/v1/devices", headers=_machine()).json()

        assert listed["devices"] == []
        assert listed["count"] == 0

    def test_revoked_devices_can_be_asked_for(self, client, store) -> None:
        _enrol(store, "phone-one")
        store.revoke(store.list()[0].id)

        listed = client.get(
            "/v1/devices", params={"include_revoked": "true"}, headers=_machine()
        ).json()

        assert [d["name"] for d in listed["devices"]] == ["phone-one"]

    def test_a_device_can_be_revoked_over_http(self, client, store) -> None:
        key = _enrol(store, "lost-phone")
        device_id = store.list()[0].id

        response = client.delete(f"/v1/devices/{device_id}", headers=_machine())

        assert response.status_code == 200
        # Gone immediately, not at the next restart: the point of revoking a
        # lost phone is that it stops working now.
        assert client.get("/v1/devices/me", headers=_bearer(key)).status_code == 401

    def test_revoking_one_device_leaves_the_others(self, client, store) -> None:
        keep = _enrol(store, "phone-two")
        _enrol(store, "phone-one")
        doomed = next(d.id for d in store.list() if d.name == "phone-one")

        client.delete(f"/v1/devices/{doomed}", headers=_machine())

        assert client.get("/v1/devices/me", headers=_bearer(keep)).status_code == 200

    def test_revoking_an_unknown_device_is_a_404(self, client, store) -> None:
        assert (
            client.delete("/v1/devices/dev_nope", headers=_machine()).status_code == 404
        )

    def test_revoking_twice_is_a_404_the_second_time(self, client, store) -> None:
        _enrol(store, "phone-one")
        device_id = store.list()[0].id

        path = f"/v1/devices/{device_id}"

        assert client.delete(path, headers=_machine()).status_code == 200
        # Already gone. Reporting success would suggest something happened.
        assert client.delete(path, headers=_machine()).status_code == 404
