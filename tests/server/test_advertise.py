"""The address this machine hands its own devices.

Pairing used to resolve one way — Tailscale, or ``http://localhost:8000``.
localhost in a QR code is the phone talking to itself, so on any machine
without Tailscale pairing could not work and nothing said why. These tests pin
the replacement: every reachable option is offered, the unreachable one is
labelled as such, and a mode the user asked for is never silently swapped for
a different one.
"""

from __future__ import annotations

import pytest

from nira.core.config import NetworkConfig, load_config
from nira.server.advertise import (
    MODES,
    AdvertiseCandidate,
    candidates,
    lan_address,
    resolve_advertise_url,
    resolve_bind_host,
)


class _Net:
    def __init__(self, **kwargs):
        base = NetworkConfig()
        for key, value in kwargs.items():
            setattr(base, key, value)
        self.network = base

        class _Server:
            host = "127.0.0.1"
            port = 8000

        self.server = _Server()


TAILNET = AdvertiseCandidate(
    kind="tailnet-dns", host="box.tail1234.ts.net", stable=True
)
SERVE = AdvertiseCandidate(
    kind="tailscale-serve",
    host="box.tail1234.ts.net",
    scheme="https",
    secure_context=True,
    stable=True,
    port_from_server=False,
)
LAN = AdvertiseCandidate(kind="lan", host="192.168.1.20")
LOOPBACK = AdvertiseCandidate(
    kind="loopback", host="127.0.0.1", reachable_off_machine=False, secure_context=True
)


@pytest.fixture
def no_tailnet(monkeypatch):
    from nira.server import advertise

    monkeypatch.setattr(advertise, "_tailnet_candidates", lambda timeout=5.0: [])
    return advertise


@pytest.fixture
def with_tailnet(monkeypatch):
    from nira.server import advertise

    monkeypatch.setattr(advertise, "_tailnet_candidates", lambda timeout=5.0: [TAILNET])
    return advertise


class TestUrlBuilding:
    def test_port_is_appended(self):
        assert TAILNET.url(8000) == "http://box.tail1234.ts.net:8000"

    def test_tls_fronted_address_carries_no_port(self):
        # `tailscale serve` terminates on 443; naming the app's port would
        # send the device past the terminator to a port nothing listens on.
        assert SERVE.url(8000) == "https://box.tail1234.ts.net"


class TestCandidates:
    def test_loopback_is_present_and_marked_unreachable(self, no_tailnet, monkeypatch):
        monkeypatch.setattr(no_tailnet, "lan_address", lambda: None)
        found = candidates()
        assert [c.kind for c in found] == ["loopback"]
        assert found[0].reachable_off_machine is False

    def test_lan_is_offered_when_present(self, no_tailnet, monkeypatch):
        monkeypatch.setattr(no_tailnet, "lan_address", lambda: "192.168.1.20")
        kinds = [c.kind for c in candidates()]
        assert kinds == ["lan", "loopback"]

    def test_tailnet_outranks_lan(self, with_tailnet, monkeypatch):
        monkeypatch.setattr(with_tailnet, "lan_address", lambda: "192.168.1.20")
        kinds = [c.kind for c in candidates()]
        assert kinds.index("tailnet-dns") < kinds.index("lan")

    def test_lan_says_the_address_can_change(self, no_tailnet, monkeypatch):
        monkeypatch.setattr(no_tailnet, "lan_address", lambda: "192.168.1.20")
        lan = next(c for c in candidates() if c.kind == "lan")
        assert not lan.stable
        assert "change" in lan.note.lower()


class TestLanAddress:
    def test_returns_a_real_address_or_nothing(self):
        # Whatever this machine has, it must never be loopback: handing a
        # device 127.0.0.1 is the bug the whole module is here to stop.
        address = lan_address()
        if address is not None:
            assert not address.startswith("127.")

    def test_a_closed_network_yields_none(self, monkeypatch):
        import socket as socket_mod

        class _DeadSocket:
            def settimeout(self, _):
                pass

            def connect(self, _):
                raise OSError("network is unreachable")

            def close(self):
                pass

        monkeypatch.setattr(socket_mod, "socket", lambda *a, **k: _DeadSocket())
        assert lan_address() is None


class TestResolve:
    def test_auto_prefers_tailnet(self, with_tailnet, monkeypatch):
        monkeypatch.setattr(with_tailnet, "lan_address", lambda: "192.168.1.20")
        url, chosen = resolve_advertise_url(_Net(mode="auto"), 8000)
        assert chosen.kind == "tailnet-dns"
        assert url == "http://box.tail1234.ts.net:8000"

    def test_auto_falls_to_lan_without_a_tailnet(self, no_tailnet, monkeypatch):
        monkeypatch.setattr(no_tailnet, "lan_address", lambda: "192.168.1.20")
        url, chosen = resolve_advertise_url(_Net(mode="auto"), 8000)
        assert chosen.kind == "lan"
        assert url == "http://192.168.1.20:8000"

    def test_auto_never_raises(self, no_tailnet, monkeypatch):
        monkeypatch.setattr(no_tailnet, "lan_address", lambda: None)
        url, chosen = resolve_advertise_url(_Net(mode="auto"), 8000)
        assert chosen.kind == "loopback"
        assert chosen.reachable_off_machine is False

    def test_tailscale_mode_refuses_rather_than_leaking_to_lan(
        self, no_tailnet, monkeypatch
    ):
        # Someone who asked for tailnet-only did so to keep the port off
        # whatever network the laptop is on. Falling back would defeat that
        # silently.
        monkeypatch.setattr(no_tailnet, "lan_address", lambda: "192.168.1.20")
        with pytest.raises(ValueError, match="not on a tailnet"):
            resolve_advertise_url(_Net(mode="tailscale"), 8000)

    def test_lan_mode_refuses_when_there_is_no_lan(self, no_tailnet, monkeypatch):
        monkeypatch.setattr(no_tailnet, "lan_address", lambda: None)
        with pytest.raises(ValueError, match="no local network address"):
            resolve_advertise_url(_Net(mode="lan"), 8000)

    def test_manual_uses_exactly_what_was_given(self):
        url, chosen = resolve_advertise_url(
            _Net(mode="manual", advertise_host="nira.lan"), 8000
        )
        assert url == "http://nira.lan:8000"
        assert chosen.kind == "manual"

    def test_manual_honours_scheme_and_port(self):
        url, _ = resolve_advertise_url(
            _Net(
                mode="manual",
                advertise_host="nira.example",
                advertise_scheme="https",
                advertise_port=443,
            ),
            8000,
        )
        assert url == "https://nira.example:443"

    def test_manual_without_a_host_says_what_to_do(self):
        with pytest.raises(ValueError, match="advertise_host is empty"):
            resolve_advertise_url(_Net(mode="manual"), 8000)

    def test_an_unknown_mode_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown network mode"):
            resolve_advertise_url(_Net(mode="carrier-pigeon"), 8000)

    @pytest.mark.parametrize("mode", MODES)
    def test_every_documented_mode_is_handled(self, mode, with_tailnet, monkeypatch):
        """No mode may fall through to an unhandled branch."""
        monkeypatch.setattr(with_tailnet, "lan_address", lambda: "192.168.1.20")
        config = _Net(mode=mode, advertise_host="pinned.example")
        url, _ = resolve_advertise_url(config, 8000)
        assert url.startswith("http")


class TestBindHost:
    def test_auto_does_not_widen_the_bind(self, with_tailnet, monkeypatch):
        # "auto" is the default. A default must not start listening on
        # whatever network the laptop happens to be on.
        monkeypatch.setattr(with_tailnet, "lan_address", lambda: "192.168.1.20")
        assert resolve_bind_host(_Net(mode="auto")) == "127.0.0.1"

    def test_explicit_bind_wins(self):
        assert resolve_bind_host(_Net(mode="auto", bind_host="0.0.0.0")) == "0.0.0.0"

    def test_lan_mode_binds_the_lan_address(self, no_tailnet, monkeypatch):
        monkeypatch.setattr(no_tailnet, "lan_address", lambda: "192.168.1.20")
        assert resolve_bind_host(_Net(mode="lan")) == "192.168.1.20"

    def test_manual_hostname_does_not_become_a_bind_address(self):
        # A name the router resolves is not necessarily an address this
        # machine can bind; binding a name we do not own fails at startup.
        assert resolve_bind_host(_Net(mode="manual", advertise_host="nira.lan")) == (
            "127.0.0.1"
        )

    def test_manual_foreign_ip_is_not_bound(self):
        assert resolve_bind_host(_Net(mode="manual", advertise_host="203.0.113.9")) == (
            "127.0.0.1"
        )


def test_the_default_config_resolves_to_something(tmp_path, monkeypatch):
    """A fresh install must produce a usable answer with no configuration."""
    monkeypatch.setenv("NIRA_CONFIG", str(tmp_path / "config.toml"))
    config = load_config()
    assert config.network.mode == "auto"
    url, _ = resolve_advertise_url(config, 8000)
    assert url.startswith("http")
