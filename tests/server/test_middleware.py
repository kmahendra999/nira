"""Tests for security middleware -- HTTP security headers."""

from __future__ import annotations

from unittest.mock import patch

from nira.server.middleware import SECURITY_HEADERS, create_security_middleware


class TestSecurityHeaders:
    """Tests for security headers middleware."""

    def test_headers_dict(self) -> None:
        """Verify SECURITY_HEADERS has all expected keys."""
        expected_keys = {
            "X-Content-Type-Options",
            "X-Frame-Options",
            "X-XSS-Protection",
            "Strict-Transport-Security",
            "Referrer-Policy",
            "Permissions-Policy",
            "Content-Security-Policy",
        }
        assert set(SECURITY_HEADERS.keys()) == expected_keys

    def test_create_middleware_without_starlette(self) -> None:
        """When starlette is not available, returns None."""
        import importlib

        import nira.server.middleware as mod

        blocked = {
            "starlette": None,
            "starlette.middleware": None,
            "starlette.middleware.base": None,
            "starlette.requests": None,
            "starlette.responses": None,
        }
        with patch.dict("sys.modules", blocked):
            importlib.reload(mod)
            result = mod.create_security_middleware()
            assert result is None
            # Reload again to restore normal state
            importlib.reload(mod)

    def test_create_middleware_with_starlette(self) -> None:
        """When starlette is available, returns a class."""
        middleware_cls = create_security_middleware()
        if middleware_cls is None:
            # starlette not installed -- skip
            import pytest

            pytest.skip("starlette not available")
        assert middleware_cls is not None
        assert callable(middleware_cls)

    def test_middleware_adds_headers(self) -> None:
        """Middleware adds all security headers to responses."""
        import pytest

        fastapi = pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient

        app = fastapi.FastAPI()

        middleware_cls = create_security_middleware()
        assert middleware_cls is not None
        app.add_middleware(middleware_cls)

        @app.get("/test")
        def test_endpoint() -> dict:
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/test")
        assert resp.status_code == 200

        for header_name, header_value in SECURITY_HEADERS.items():
            assert resp.headers.get(header_name) == header_value, (
                f"Missing or wrong header: {header_name}"
            )

    def test_middleware_skips_options(self) -> None:
        """OPTIONS requests pass through without security headers."""
        import pytest

        fastapi = pytest.importorskip("fastapi")
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.testclient import TestClient

        app = fastapi.FastAPI()

        # Add CORS first, then security (reverse execution order)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
        middleware_cls = create_security_middleware()
        assert middleware_cls is not None
        app.add_middleware(middleware_cls)

        @app.post("/test")
        def test_endpoint() -> dict:
            return {"ok": True}

        client = TestClient(app)
        resp = client.options(
            "/test",
            headers={
                "Origin": "https://tauri.localhost",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert resp.status_code == 200
        assert "access-control-allow-origin" in resp.headers
        # Security headers should NOT be present on preflight
        assert "X-Frame-Options" not in resp.headers


class TestContentSecurityPolicy:
    """The page's own fonts and images have to be allowed to load.

    `default-src 'self' …` alone has no `data:`, and both `font-src` and
    `img-src` fall back to it — so KaTeX's data-URI maths fonts were refused
    and every formula in a reply rendered in a fallback face, while the page's
    inline-SVG background never appeared. The console said so on every load
    and nobody was reading it.
    """

    def policy(self) -> str:
        from nira.server.middleware import SECURITY_HEADERS

        return SECURITY_HEADERS["Content-Security-Policy"]

    def test_fonts_may_be_inline_data(self) -> None:
        assert "font-src 'self' data:" in self.policy()

    def test_images_may_be_inline_data_or_blobs(self) -> None:
        assert "img-src 'self' data: blob:" in self.policy()

    def test_recorded_audio_may_be_a_blob(self) -> None:
        # The digest player and anything recorded in the browser.
        assert "media-src" in self.policy()
        assert "blob:" in self.policy().split("media-src")[1]

    def test_scripts_may_not_be_data_uris(self) -> None:
        # The reason data: is added per-directive rather than to default-src:
        # a data: font or image is inert, a data: script is not.
        default = self.policy().split(";")[0]
        assert "default-src" in default
        assert "data:" not in default

    def test_everything_still_defaults_to_this_origin(self) -> None:
        assert self.policy().startswith("default-src 'self'")


class TestTheRealAppSendsThem:
    """`create_app` itself, not a FastAPI app assembled by a test.

    The middleware is attached inside a `try/except Exception` that logs at
    DEBUG and carries on. If that ever swallowed something, every response
    would go out with no security headers and nothing would say so -- which is
    exactly how `website/nginx.conf` came to serve none of them for months.
    The other tests here build their own app and add the middleware by hand,
    so they cannot see that failure.
    """

    def test_health_carries_every_security_header(self) -> None:
        from unittest.mock import MagicMock

        from fastapi.testclient import TestClient

        from nira.server.app import create_app
        from nira.server.middleware import SECURITY_HEADERS

        client = TestClient(create_app(MagicMock(), "test-model"))
        response = client.get("/health")

        assert response.status_code == 200
        missing = [h for h in SECURITY_HEADERS if h not in response.headers]
        assert not missing, f"create_app() served no {missing}"

    def test_the_values_are_the_ones_declared(self) -> None:
        from unittest.mock import MagicMock

        from fastapi.testclient import TestClient

        from nira.server.app import create_app
        from nira.server.middleware import SECURITY_HEADERS

        client = TestClient(create_app(MagicMock(), "test-model"))
        response = client.get("/health")

        for header, value in SECURITY_HEADERS.items():
            assert response.headers[header] == value, header
