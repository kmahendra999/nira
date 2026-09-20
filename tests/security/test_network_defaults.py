"""Tests for secure network defaults (Section 1 of security hardening)."""

from __future__ import annotations

import ipaddress

import pytest


class TestServerConfigDefaults:
    """ServerConfig should bind to loopback by default."""

    def test_default_host_is_loopback(self) -> None:
        from nira.core.config import ServerConfig

        cfg = ServerConfig()
        assert cfg.host == "127.0.0.1"

    def test_default_port_unchanged(self) -> None:
        from nira.core.config import ServerConfig

        cfg = ServerConfig()
        assert cfg.port == 8000

    def test_cors_origins_default(self) -> None:
        from nira.core.config import ServerConfig

        cfg = ServerConfig()
        assert isinstance(cfg.cors_origins, list)
        assert "http://localhost:3000" in cfg.cors_origins
        assert "http://localhost:5173" in cfg.cors_origins
        # All three Tauri 2 production webview origins must be allowed
        # so the desktop chat stream works on every platform.
        assert "tauri://localhost" in cfg.cors_origins
        assert "http://tauri.localhost" in cfg.cors_origins
        assert "https://tauri.localhost" in cfg.cors_origins
        assert "*" not in cfg.cors_origins


class TestSecurityConfigDefaults:
    """SecurityConfig should default to redact mode with rate limiting."""

    def test_default_mode_is_redact(self) -> None:
        from nira.core.config import SecurityConfig

        cfg = SecurityConfig()
        assert cfg.mode == "redact"

    def test_rate_limiting_enabled_by_default(self) -> None:
        from nira.core.config import SecurityConfig

        cfg = SecurityConfig()
        assert cfg.rate_limit_enabled is True

    def test_bypass_defaults_conservative(self) -> None:
        from nira.core.config import SecurityConfig

        cfg = SecurityConfig()
        assert cfg.local_engine_bypass is False
        assert cfg.local_tool_bypass is False

    def test_profile_default_empty(self) -> None:
        from nira.core.config import SecurityConfig

        cfg = SecurityConfig()
        assert cfg.profile == ""


def _is_loopback(host: str) -> bool:
    """Check if a host string is a loopback address."""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host in ("localhost", "")


class TestNonLoopbackAuthEnforcement:
    """Server must require API key when binding non-loopback."""

    def test_loopback_allows_no_key(self) -> None:
        assert _is_loopback("127.0.0.1")

    def test_wildcard_is_not_loopback(self) -> None:
        assert not _is_loopback("0.0.0.0")

    def test_non_loopback_requires_key(self) -> None:
        starlette = pytest.importorskip("starlette")  # noqa: F841
        from nira.server.auth_middleware import check_bind_safety

        try:
            check_bind_safety("0.0.0.0", api_key="")
            assert False, "Should have raised"
        except SystemExit:
            pass

    def test_non_loopback_with_key_ok(self) -> None:
        starlette = pytest.importorskip("starlette")  # noqa: F841
        from nira.server.auth_middleware import check_bind_safety

        check_bind_safety("0.0.0.0", api_key="oj_sk_test123")


class TestCORSConfiguration:
    """CORS should use configured origins, not wildcard."""

    def test_create_app_uses_configured_origins(self) -> None:
        pytest.importorskip("fastapi")
        from unittest.mock import MagicMock

        from fastapi.testclient import TestClient

        from nira.server.app import create_app

        mock_engine = MagicMock()
        mock_engine.health.return_value = True
        mock_engine.list_models.return_value = ["test-model"]

        app = create_app(
            mock_engine,
            "test-model",
            cors_origins=["http://localhost:3000"],
        )
        client = TestClient(app)

        resp = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert (
            resp.headers.get("access-control-allow-origin") == "http://localhost:3000"
        )

        resp2 = client.options(
            "/health",
            headers={
                "Origin": "http://evil.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp2.headers.get("access-control-allow-origin") != "http://evil.com"

    def test_default_origins_allow_tauri_webview(self) -> None:
        """Regression: Tauri 2 desktop chat-completions stream must not
        be blocked by CORS preflight on any platform.

        macOS / Linux use ``tauri://localhost``; Windows / Android use
        ``http://tauri.localhost`` (or the ``https`` variant when
        ``windows.useHttpsScheme`` is enabled). The default origin list
        in ``create_app`` must accept all three so the user does not
        see "Stream error: Failed to fetch" in the desktop logs.
        """
        pytest.importorskip("fastapi")
        from unittest.mock import MagicMock

        from fastapi.testclient import TestClient

        from nira.server.app import create_app

        mock_engine = MagicMock()
        mock_engine.health.return_value = True
        mock_engine.list_models.return_value = ["test-model"]

        app = create_app(mock_engine, "test-model")
        client = TestClient(app)

        for origin in (
            "tauri://localhost",
            "http://tauri.localhost",
            "https://tauri.localhost",
        ):
            resp = client.options(
                "/v1/chat/completions",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                },
            )
            assert resp.headers.get("access-control-allow-origin") == origin, (
                f"Tauri origin {origin} was not allowed by default CORS list"
            )


class TestDocumentedBindDefaultMatchesCode:
    """The docs must not disagree with ServerConfig about the bind address.

    They did: docs/deployment/api-server.md documented the default as
    "0.0.0.0" in its CLI table, its startup banner and its sample
    config.toml, and docs/getting-started/configuration.md shipped a full
    example config with host = "0.0.0.0". Anyone copying those exposed a
    server that fronts an agent with shell, file and browser tools.

    A wrong default in prose is a real vulnerability, so it is worth a test.
    """

    _DOCS = (
        "docs/deployment/api-server.md",
        "docs/getting-started/configuration.md",
    )

    def _repo_root(self):
        from pathlib import Path

        return Path(__file__).resolve().parents[2]

    def test_sample_server_blocks_use_the_real_default(self) -> None:
        import re

        from nira.core.config import ServerConfig

        default_host = ServerConfig().host

        for rel in self._DOCS:
            text = (self._repo_root() / rel).read_text(encoding="utf-8")
            # Every ``[server]`` TOML block that sets host must set it to the
            # real default; these blocks are what readers copy verbatim.
            for block in re.findall(r"\[server\]\n(.*?)(?:\n\[|\n```)", text, re.S):
                for line in block.splitlines():
                    if line.strip().startswith("host"):
                        assert f'"{default_host}"' in line, (
                            f"{rel} documents host as {line.strip()!r}, "
                            f"but ServerConfig defaults to {default_host!r}"
                        )

    def test_no_doc_claims_the_default_is_the_wildcard(self) -> None:
        from nira.core.config import ServerConfig

        assert ServerConfig().host != "0.0.0.0", "guard assumes a loopback default"

        for rel in self._DOCS:
            text = (self._repo_root() / rel).read_text(encoding="utf-8")
            for line in text.splitlines():
                lowered = line.lower()
                if "0.0.0.0" in lowered and "default" in lowered:
                    # Describing a container command that passes 0.0.0.0 is
                    # fine; asserting it is the *config* default is not.
                    assert "config default is" in lowered or "image" in lowered, (
                        f"{rel} appears to document 0.0.0.0 as a default: {line.strip()!r}"
                    )
