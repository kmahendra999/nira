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
        # Both halves, because an empty PATH no longer means "not installed":
        # the binary is also looked for where each platform's installer puts
        # it, so clearing only `which` still finds a real Tailscale on a
        # machine that has one.
        monkeypatch.setattr("nira.server.tailnet.shutil.which", lambda _: None)
        monkeypatch.setattr("nira.server.tailnet._FALLBACK_PATHS", {})
        monkeypatch.delenv("NIRA_TAILSCALE_BIN", raising=False)

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


class TestFindingTheBinary:
    """Tailscale's CLI is not always on PATH, and the failure is silent.

    macOS is the case that matters: the App Store and standalone builds ship
    the binary inside the .app bundle and never touch PATH, so a Mac happily
    on a tailnet looks exactly like one without Tailscale installed. What
    follows is not an error — pairing quietly falls back to a LAN address that
    stops working the moment the laptop moves, which is the whole failure this
    module exists to prevent.
    """

    def test_path_is_preferred(self, monkeypatch, tmp_path) -> None:
        from nira.server import tailnet

        on_path = tmp_path / "tailscale"
        on_path.write_text("")
        monkeypatch.setattr(tailnet.shutil, "which", lambda _name: str(on_path))
        monkeypatch.delenv("NIRA_TAILSCALE_BIN", raising=False)

        assert tailnet.tailscale_binary() == str(on_path)

    def test_the_mac_app_bundle_is_found(self, monkeypatch, tmp_path) -> None:
        from nira.server import tailnet

        bundled = tmp_path / "Tailscale.app/Contents/MacOS/Tailscale"
        bundled.parent.mkdir(parents=True)
        bundled.write_text("")
        monkeypatch.setattr(tailnet.shutil, "which", lambda _name: None)
        monkeypatch.setattr(tailnet.sys, "platform", "darwin")
        monkeypatch.setattr(tailnet, "_FALLBACK_PATHS", {"darwin": (str(bundled),)})
        monkeypatch.delenv("NIRA_TAILSCALE_BIN", raising=False)

        assert tailnet.tailscale_binary() == str(bundled)
        assert tailnet.tailscale_available() is True

    def test_a_windows_install_directory_is_found(self, monkeypatch, tmp_path) -> None:
        from nira.server import tailnet

        installed = tmp_path / "tailscale.exe"
        installed.write_text("")
        monkeypatch.setattr(tailnet.shutil, "which", lambda _name: None)
        monkeypatch.setattr(tailnet.sys, "platform", "win32")
        monkeypatch.setattr(tailnet, "_FALLBACK_PATHS", {"win32": (str(installed),)})
        monkeypatch.delenv("NIRA_TAILSCALE_BIN", raising=False)

        assert tailnet.tailscale_binary() == str(installed)

    def test_a_path_that_does_not_exist_is_not_offered(
        self, monkeypatch, tmp_path
    ) -> None:
        from nira.server import tailnet

        monkeypatch.setattr(tailnet.shutil, "which", lambda _name: None)
        monkeypatch.setattr(tailnet.sys, "platform", "darwin")
        monkeypatch.setattr(
            tailnet, "_FALLBACK_PATHS", {"darwin": (str(tmp_path / "nope"),)}
        )
        monkeypatch.delenv("NIRA_TAILSCALE_BIN", raising=False)

        # Returning a path that is not there would turn "Tailscale is not
        # installed" into "every tailscale command fails", which is harder to
        # read and reported in a worse place.
        assert tailnet.tailscale_binary() is None
        assert tailnet.tailscale_available() is False

    def test_an_unknown_platform_falls_back_to_path_alone(self, monkeypatch) -> None:
        from nira.server import tailnet

        monkeypatch.setattr(tailnet.shutil, "which", lambda _name: None)
        monkeypatch.setattr(tailnet.sys, "platform", "freebsd13")
        monkeypatch.delenv("NIRA_TAILSCALE_BIN", raising=False)

        assert tailnet.tailscale_binary() is None

    def test_an_override_wins(self, monkeypatch, tmp_path) -> None:
        from nira.server import tailnet

        custom = tmp_path / "my-tailscale"
        custom.write_text("")
        monkeypatch.setattr(tailnet.shutil, "which", lambda _name: "/usr/bin/tailscale")
        monkeypatch.setenv("NIRA_TAILSCALE_BIN", str(custom))

        assert tailnet.tailscale_binary() == str(custom)

    def test_a_broken_override_is_not_silently_ignored(
        self, monkeypatch, tmp_path
    ) -> None:
        from nira.server import tailnet

        monkeypatch.setattr(tailnet.shutil, "which", lambda _name: "/usr/bin/tailscale")
        monkeypatch.setenv("NIRA_TAILSCALE_BIN", str(tmp_path / "missing"))

        # Falling back to PATH would run a different binary than the one the
        # user named, which is worse than reporting nothing.
        assert tailnet.tailscale_binary() is None

    def test_the_found_binary_is_the_one_invoked(self, monkeypatch, tmp_path) -> None:
        from nira.server import tailnet

        bundled = tmp_path / "Tailscale"
        bundled.write_text("")
        monkeypatch.setenv("NIRA_TAILSCALE_BIN", str(bundled))
        invoked: list[list[str]] = []

        def fake_run(cmd, **kwargs):  # noqa: ANN001, ANN202
            invoked.append(cmd)
            raise OSError("not really running it")

        monkeypatch.setattr(tailnet.subprocess, "run", fake_run)
        tailnet.get_identity()

        # Invoking the bare name would fail on exactly the machines the
        # fallback exists for.
        assert invoked and invoked[0][0] == str(bundled)
