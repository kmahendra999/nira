"""``nira device`` — pairing, listing, revoking."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from nira.cli.device_cmd import device
from nira.devices import DeviceStore
from nira.server.advertise import AdvertiseCandidate


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr("nira.cli.device_cmd.get_config_dir", lambda: tmp_path / "home")


@pytest.fixture
def store(tmp_path):
    registry = DeviceStore(tmp_path / "home" / "devices.db")
    yield registry
    registry.close()


def _run(*args):
    return CliRunner().invoke(device, list(args))


class TestPair:
    def test_prints_a_single_use_token(self) -> None:
        result = _run("pair", "Pixel 8")

        assert result.exit_code == 0
        assert "nira_en_" in result.output
        assert "Single use" in result.output

    def test_default_scopes_exclude_approve(self) -> None:
        """Pairing a phone must not silently let it approve anything."""
        result = _run("pair", "Pixel 8")

        assert "ask, watch" in result.output
        assert "approve" not in result.output

    def test_scopes_can_be_requested(self) -> None:
        result = _run("pair", "Laptop", "--scope", "ask", "--scope", "approve")

        assert result.exit_code == 0
        assert "approve" in result.output

    def test_an_unknown_scope_is_rejected(self) -> None:
        result = _run("pair", "Laptop", "--scope", "superuser")

        assert result.exit_code != 0

    def test_the_token_is_redeemable(self, store) -> None:
        """End to end: what the CLI prints is what a device can claim."""
        output = _run("pair", "Pixel 8").output
        token = next(word for word in output.split() if word.startswith("nira_en_"))

        paired, key = store.redeem_enrollment(token, platform="android")

        assert paired.name == "Pixel 8"
        assert store.authenticate(key).id == paired.id


class TestList:
    def test_empty_registry_says_so(self) -> None:
        assert "No devices paired" in _run("list").output

    def test_shows_a_paired_device(self, store) -> None:
        enrollment = store.create_enrollment("Pixel 8")
        store.redeem_enrollment(enrollment.token, platform="android")

        result = _run("list")

        assert "Pixel 8" in result.output

    def test_revoked_devices_are_hidden_by_default(self, store) -> None:
        enrollment = store.create_enrollment("Old Phone")
        paired, _ = store.redeem_enrollment(enrollment.token)
        store.revoke(paired.id)

        assert "Old Phone" not in _run("list").output
        assert "Old Phone" in _run("list", "--all").output


class TestRevoke:
    def test_revokes_a_device(self, store) -> None:
        enrollment = store.create_enrollment("Pixel 8")
        paired, key = store.redeem_enrollment(enrollment.token)

        result = _run("revoke", paired.id)

        assert result.exit_code == 0
        assert store.authenticate(key) is None

    def test_an_unknown_device_exits_nonzero(self) -> None:
        assert _run("revoke", "dev_nope").exit_code == 1


class TestScopes:
    def test_replaces_a_devices_scopes(self, store) -> None:
        enrollment = store.create_enrollment("Laptop")
        paired, _ = store.redeem_enrollment(enrollment.token)

        result = _run("scopes", paired.id, "ask", "approve")

        assert result.exit_code == 0
        assert store.get(paired.id).can("approve") is True

    def test_an_unknown_scope_is_rejected(self, store) -> None:
        enrollment = store.create_enrollment("Laptop")
        paired, _ = store.redeem_enrollment(enrollment.token)

        result = _run("scopes", paired.id, "superuser")

        assert result.exit_code == 1
        assert "Unknown scope" in result.output


class TestPairingPayload:
    def test_the_qr_encodes_a_reachable_url_and_the_token(self, monkeypatch) -> None:
        """A phone needs somewhere to send the token, not just the token."""
        captured = {}

        def _capture(payload, console):
            captured["payload"] = payload
            return True

        monkeypatch.setattr("nira.cli.device_cmd._render_qr", _capture)
        monkeypatch.setattr(
            "nira.cli.device_cmd._pairing_target",
            lambda port: (
                f"http://host:{port}",
                AdvertiseCandidate(kind="lan", host="host"),
            ),
        )

        _run("pair", "Pixel 8", "--port", "9000")

        payload = json.loads(captured["payload"])
        assert payload["url"] == "http://host:9000"
        assert payload["token"].startswith("nira_en_")
        assert payload["name"] == "Pixel 8"

    def test_without_a_tailnet_it_uses_the_local_network(self, monkeypatch) -> None:
        """It used to fall back to localhost — a QR the phone cannot follow.

        See tests/cli/test_network_cmd.py for the case where there is no
        network at all, which now says so instead of pretending.
        """
        from nira.server import advertise

        monkeypatch.setattr(advertise, "_tailnet_candidates", lambda timeout=5.0: [])
        monkeypatch.setattr(advertise, "lan_address", lambda: "192.168.1.20")

        from nira.cli.device_cmd import _pairing_target

        url, candidate = _pairing_target(8000)
        assert url == "http://192.168.1.20:8000"
        assert candidate.reachable_off_machine


class TestSecureContextGuidance:
    """A plain http pairing address cannot install the web app.

    Service workers require a secure context, so a MagicDNS name served over
    http is reachable but not installable — a distinction a user has no way to
    discover on their own.
    """

    def test_https_is_preferred_when_tailscale_serve_is_configured(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            "nira.server.tailnet.https_serve_target",
            lambda *a, **k: "https://box.tail0.ts.net",
        )

        from nira.cli.device_cmd import _pairing_target

        url, candidate = _pairing_target(8000)
        assert url == "https://box.tail0.ts.net"
        assert candidate.secure_context

    def test_pairing_explains_the_limitation_on_http(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "nira.server.tailnet.https_serve_target", lambda *a, **k: None
        )
        monkeypatch.setattr(
            "nira.server.tailnet.get_identity",
            lambda *a, **k: SimpleNamespace(dns_name="box.ts.net", ipv4="100.1.2.3"),
        )

        result = _run("pair", "Pixel 8")

        assert "insecure context" in result.output
        assert "tailscale serve" in result.output

    def test_no_warning_when_the_address_is_already_https(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "nira.server.tailnet.https_serve_target",
            lambda *a, **k: "https://box.tail0.ts.net",
        )

        result = _run("pair", "Pixel 8")

        assert "insecure context" not in result.output
