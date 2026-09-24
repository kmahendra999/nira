"""``nira network`` and the address pairing hands out.

The bug: ``nira device pair`` resolved Tailscale or fell back to
``http://localhost:8000``. A phone scanning that QR code points at itself, so
on any machine without Tailscale pairing could not work — and the output said
nothing about why. It also burned a single-use enrollment token doing it.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from nira.cli.device_cmd import device
from nira.cli.network_cmd import network
from nira.server.advertise import AdvertiseCandidate


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text("", encoding="utf-8")
    monkeypatch.setenv("NIRA_CONFIG", str(path))
    monkeypatch.setenv("NIRA_HOME", str(tmp_path))
    return path


@pytest.fixture
def no_network(monkeypatch):
    """A machine with no tailnet and no LAN — the worst case."""
    from nira.server import advertise

    monkeypatch.setattr(advertise, "_tailnet_candidates", lambda timeout=5.0: [])
    monkeypatch.setattr(advertise, "lan_address", lambda: None)


@pytest.fixture
def lan_only(monkeypatch):
    from nira.server import advertise

    monkeypatch.setattr(advertise, "_tailnet_candidates", lambda timeout=5.0: [])
    monkeypatch.setattr(advertise, "lan_address", lambda: "192.168.1.20")


class TestNetworkStatus:
    def test_lists_the_options(self, config_file, lan_only):
        result = CliRunner().invoke(network, ["status"])
        assert result.exit_code == 0, result.output
        assert "192.168.1.20" in result.output
        assert "auto" in result.output

    def test_says_when_nothing_is_reachable(self, config_file, no_network):
        result = CliRunner().invoke(network, ["status"])
        assert result.exit_code == 0
        assert "No other device can reach" in result.output


class TestNetworkSet:
    def test_a_host_implies_manual(self, config_file):
        result = CliRunner().invoke(network, ["set", "--host", "nira.lan"])
        assert result.exit_code == 0, result.output
        from nira.core.config import load_config

        config = load_config()
        assert config.network.mode == "manual"
        assert config.network.advertise_host == "nira.lan"
        assert "http://nira.lan" in result.output

    def test_manual_without_a_host_is_refused(self, config_file):
        result = CliRunner().invoke(network, ["set", "--mode", "manual"])
        assert result.exit_code == 1
        assert "needs an address" in result.output

    def test_nothing_to_change_is_not_a_silent_success(self, config_file):
        result = CliRunner().invoke(network, ["set"])
        assert result.exit_code == 1
        assert "Nothing to change" in result.output

    def test_reset_returns_to_auto(self, config_file):
        runner = CliRunner()
        runner.invoke(network, ["set", "--host", "nira.lan"])
        result = runner.invoke(network, ["reset"])
        assert result.exit_code == 0
        from nira.core.config import load_config

        config = load_config()
        assert config.network.mode == "auto"
        assert config.network.advertise_host == ""


class TestPairingAddress:
    def test_pairing_uses_the_lan_address_when_there_is_no_tailnet(
        self, config_file, lan_only, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("NIRA_HOME", str(tmp_path))
        result = CliRunner().invoke(device, ["pair", "phone"])
        assert result.exit_code == 0, result.output
        assert "192.168.1.20" in result.output
        assert "localhost" not in result.output, (
            "a QR code pointing at localhost is the phone talking to itself"
        )

    def test_pairing_says_so_when_no_device_can_reach_this_machine(
        self, config_file, no_network, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("NIRA_HOME", str(tmp_path))
        result = CliRunner().invoke(device, ["pair", "phone"])
        assert result.exit_code == 0, result.output
        assert "points at this machine only" in result.output
        assert "nira network set" in result.output

    def test_a_manual_address_reaches_the_payload(
        self, config_file, no_network, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("NIRA_HOME", str(tmp_path))
        runner = CliRunner()
        runner.invoke(network, ["set", "--host", "nira.example", "--port", "9000"])
        result = runner.invoke(device, ["pair", "phone"])
        assert result.exit_code == 0, result.output
        assert "http://nira.example:9000" in result.output

    def test_an_unsatisfiable_mode_does_not_burn_a_token(
        self, config_file, no_network, monkeypatch, tmp_path
    ):
        # An enrollment is single-use and expires in ten minutes. Creating one
        # and then discovering there is no address costs the user a token and
        # tells them nothing.
        monkeypatch.setenv("NIRA_HOME", str(tmp_path))
        runner = CliRunner()
        runner.invoke(network, ["set", "--mode", "tailscale"])
        result = runner.invoke(device, ["pair", "phone"])
        assert result.exit_code == 1
        assert "tailnet" in result.output
        assert "Token" not in result.output

        listed = runner.invoke(device, ["list"])
        assert "No devices paired" in listed.output or "phone" not in listed.output


def test_tls_fronted_address_is_handed_out_without_a_port(
    config_file, monkeypatch, tmp_path
):
    """`tailscale serve` terminates on 443; appending the app port breaks it."""
    from nira.server import advertise

    monkeypatch.setenv("NIRA_HOME", str(tmp_path))
    monkeypatch.setattr(
        advertise,
        "_tailnet_candidates",
        lambda timeout=5.0: [
            AdvertiseCandidate(
                kind="tailscale-serve",
                host="box.tail1234.ts.net",
                scheme="https",
                secure_context=True,
                stable=True,
                port_from_server=False,
            )
        ],
    )
    result = CliRunner().invoke(device, ["pair", "phone"])
    assert result.exit_code == 0, result.output
    assert "https://box.tail1234.ts.net" in result.output
    assert "ts.net:8000" not in result.output

    payload_line = [
        line for line in result.output.splitlines() if line.strip().startswith("URL")
    ]
    assert payload_line, result.output
    # And the same address is what the device actually receives.
    assert "https://box.tail1234.ts.net" in payload_line[0]
    json.dumps({"ok": True})  # payload is JSON-encoded elsewhere; smoke only
