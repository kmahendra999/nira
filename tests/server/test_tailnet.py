"""Resolving this machine's Tailscale address.

For a personal mesh the tailnet interface beats 0.0.0.0: binding every
interface exposes an agent with shell, file and browser tools to whatever
network the laptop is currently on, and that exposure follows the machine
around. What a tailnet does not do is authenticate anyone — it can be shared
with other accounts — so reaching the port still proves nothing.
"""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from nira.server.tailnet import TailnetIdentity, get_identity, is_tailnet_address

_STATUS = {
    "Self": {
        "TailscaleIPs": ["100.123.66.19", "fd7a:115c:a1e0::c338:4214"],
        "DNSName": "diubuntu.tail0ab740.ts.net.",
    },
    "CurrentTailnet": {"Name": "someone@example.com"},
}


def _stub_tailscale(monkeypatch, *, stdout="", returncode=0, exc=None):
    monkeypatch.setattr(
        "nira.server.tailnet.shutil.which", lambda _: "/usr/bin/tailscale"
    )

    def _run(*args, **kwargs):
        if exc is not None:
            raise exc
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", _run)


class TestIdentity:
    def test_prefers_the_ipv4_address(self, monkeypatch) -> None:
        _stub_tailscale(monkeypatch, stdout=json.dumps(_STATUS))

        assert get_identity().ipv4 == "100.123.66.19"

    def test_strips_the_trailing_dot_from_magicdns(self, monkeypatch) -> None:
        _stub_tailscale(monkeypatch, stdout=json.dumps(_STATUS))

        assert get_identity().dns_name == "diubuntu.tail0ab740.ts.net"

    def test_url_prefers_the_stable_name(self) -> None:
        """MagicDNS keeps resolving as the machine changes networks — exactly
        what a paired phone has to survive."""
        identity = TailnetIdentity(ipv4="100.1.2.3", dns_name="box.ts.net")

        assert identity.url == "http://box.ts.net"

    def test_url_falls_back_to_the_address(self) -> None:
        assert TailnetIdentity(ipv4="100.1.2.3", dns_name="").url == "http://100.1.2.3"


class TestUnavailable:
    """Every "not on a tailnet" case looks the same to the caller."""

    def test_not_installed(self, monkeypatch) -> None:
        monkeypatch.setattr("nira.server.tailnet.shutil.which", lambda _: None)

        assert get_identity() is None

    def test_daemon_not_running(self, monkeypatch) -> None:
        _stub_tailscale(monkeypatch, returncode=1)

        assert get_identity() is None

    def test_unparseable_output(self, monkeypatch) -> None:
        _stub_tailscale(monkeypatch, stdout="not json")

        assert get_identity() is None

    def test_subprocess_failure(self, monkeypatch) -> None:
        _stub_tailscale(monkeypatch, exc=OSError("boom"))

        assert get_identity() is None

    def test_logged_out_node_has_no_address(self, monkeypatch) -> None:
        _stub_tailscale(monkeypatch, stdout=json.dumps({"Self": {"TailscaleIPs": []}}))

        assert get_identity() is None

    def test_ipv6_only_is_not_usable_as_a_bind_host(self, monkeypatch) -> None:
        _stub_tailscale(
            monkeypatch,
            stdout=json.dumps({"Self": {"TailscaleIPs": ["fd7a:115c:a1e0::1"]}}),
        )

        assert get_identity() is None


class TestAddressRange:
    def test_recognises_the_cgnat_range(self) -> None:
        assert is_tailnet_address("100.123.66.19") is True

    def test_rejects_a_lan_address(self) -> None:
        assert is_tailnet_address("192.168.1.5") is False

    def test_rejects_loopback(self) -> None:
        assert is_tailnet_address("127.0.0.1") is False

    def test_rejects_a_hostname(self) -> None:
        assert is_tailnet_address("box.ts.net") is False


class TestBindSafety:
    def test_a_tailnet_bind_still_requires_a_key(self) -> None:
        """Reaching the port over a tailnet proves nothing about who is
        knocking — a tailnet can be shared with accounts that are not yours."""
        from nira.server.auth_middleware import check_bind_safety

        with pytest.raises(SystemExit):
            check_bind_safety("100.123.66.19", api_key="")

    def test_a_tailnet_bind_with_a_key_is_allowed(self) -> None:
        from nira.server.auth_middleware import check_bind_safety

        check_bind_safety("100.123.66.19", api_key="nira_sk_test")


class TestHttpsServeTarget:
    """`tailscale serve` is what makes the web app installable on a phone.

    A browser treats a plain http MagicDNS origin as an insecure context, and
    an insecure context may not register a service worker — so the PWA will
    not install and will not work offline, however reachable the port is.
    """

    def _stub_serve(self, monkeypatch, *, stdout="", returncode=0):
        monkeypatch.setattr(
            "nira.server.tailnet.shutil.which", lambda _: "/usr/bin/tailscale"
        )
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: SimpleNamespace(
                returncode=returncode, stdout=stdout, stderr=""
            ),
        )

    def test_returns_the_https_origin_when_configured(self, monkeypatch) -> None:
        from nira.server.tailnet import https_serve_target

        self._stub_serve(
            monkeypatch,
            stdout=json.dumps({"Web": {"diubuntu.tail0ab740.ts.net:443": {}}}),
        )

        assert https_serve_target() == "https://diubuntu.tail0ab740.ts.net"

    def test_returns_none_when_serve_is_not_configured(self, monkeypatch) -> None:
        from nira.server.tailnet import https_serve_target

        self._stub_serve(monkeypatch, stdout="")

        assert https_serve_target() is None

    def test_returns_none_when_the_command_fails(self, monkeypatch) -> None:
        from nira.server.tailnet import https_serve_target

        self._stub_serve(monkeypatch, returncode=1, stdout="{}")

        assert https_serve_target() is None

    def test_returns_none_on_unparseable_output(self, monkeypatch) -> None:
        from nira.server.tailnet import https_serve_target

        self._stub_serve(monkeypatch, stdout="not json")

        assert https_serve_target() is None

    def test_returns_none_without_tailscale(self, monkeypatch) -> None:
        from nira.server.tailnet import https_serve_target

        monkeypatch.setattr("nira.server.tailnet.shutil.which", lambda _: None)

        assert https_serve_target() is None
