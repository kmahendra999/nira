"""Per-caller HTTP request rate limiting.

The existing limiter gates *tool calls* — whether an agent may run a given
tool. Nothing gated HTTP requests, so a caller with a valid key could issue
completions as fast as the machine accepted them, and an unauthenticated flood
of a public path cost a connection each with no ceiling.

Survivable on loopback. Once the server binds to a tailnet — shared with
devices, possibly with accounts that are not yours — it is the difference
between one misbehaving client and an unusable machine.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi", reason="nira[server] not installed")

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from nira.server.rate_limit_middleware import RateLimitMiddleware


def _app(limit: int = 5):
    async def _ok(request):
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/v1/x", _ok), Route("/health", _ok)])
    app.add_middleware(RateLimitMiddleware, requests_per_minute=limit)
    return app


class TestLimiting:
    def test_requests_under_the_limit_pass(self) -> None:
        client = TestClient(_app(limit=5))

        codes = [client.get("/v1/x").status_code for _ in range(5)]

        assert codes == [200] * 5

    def test_exceeding_the_limit_returns_429(self) -> None:
        client = TestClient(_app(limit=3))
        for _ in range(3):
            client.get("/v1/x")

        assert client.get("/v1/x").status_code == 429

    def test_a_retry_after_header_is_sent(self) -> None:
        """Telling a client to back off without saying how long is not much
        help to an automated one."""
        client = TestClient(_app(limit=1))
        client.get("/v1/x")

        response = client.get("/v1/x")

        assert int(response.headers["retry-after"]) >= 1

    def test_a_limit_of_zero_is_clamped_to_one(self) -> None:
        """A misconfigured zero would otherwise lock the server out entirely."""
        client = TestClient(_app(limit=0))

        assert client.get("/v1/x").status_code == 200


class TestExemptions:
    def test_health_is_never_throttled(self) -> None:
        """A supervisor uses it to decide the process is alive; throttling it
        turns a busy server into one that looks dead and gets restarted."""
        client = TestClient(_app(limit=1))
        client.get("/v1/x")
        client.get("/v1/x")

        codes = [client.get("/health").status_code for _ in range(10)]

        assert codes == [200] * 10


class TestPerCallerBuckets:
    def test_devices_are_bucketed_separately(self) -> None:
        """One phone in a retry loop must not consume every other client's
        budget."""

        async def _ok(request):
            return JSONResponse({"ok": True})

        app = Starlette(routes=[Route("/v1/x", _ok)])
        app.add_middleware(RateLimitMiddleware, requests_per_minute=2)

        class _Identify:
            """Stand in for AuthMiddleware attaching a device to the scope."""

            def __init__(self, inner):
                self.inner = inner

            async def __call__(self, scope, receive, send):
                if scope["type"] == "http":
                    header = dict(scope.get("headers") or {})
                    raw = header.get(b"x-test-device", b"")
                    scope["nira_device"] = SimpleNamespace(id=raw.decode() or "a")
                await self.inner(scope, receive, send)

        client = TestClient(_Identify(app))

        # Exhaust device A.
        for _ in range(2):
            client.get("/v1/x", headers={"X-Test-Device": "phone-a"})
        exhausted = client.get("/v1/x", headers={"X-Test-Device": "phone-a"})

        # Device B is unaffected.
        other = client.get("/v1/x", headers={"X-Test-Device": "phone-b"})

        assert exhausted.status_code == 429
        assert other.status_code == 200


class TestWindow:
    def test_old_hits_age_out_of_the_window(self, monkeypatch) -> None:
        """A sliding window, not a fixed one: a fixed window lets a caller
        send a full budget at 59s and another at 61s."""
        import nira.server.rate_limit_middleware as module

        clock = {"now": 1000.0}
        monkeypatch.setattr(module.time, "monotonic", lambda: clock["now"])

        client = TestClient(_app(limit=2))
        client.get("/v1/x")
        client.get("/v1/x")
        assert client.get("/v1/x").status_code == 429

        clock["now"] += 61.0

        assert client.get("/v1/x").status_code == 200

    def test_quiet_callers_are_pruned(self, monkeypatch) -> None:
        """A long-lived server must not keep one entry per address it has
        ever seen."""
        import nira.server.rate_limit_middleware as module

        limiter = module.RateLimitMiddleware(app=None, requests_per_minute=10)
        clock = {"now": 1000.0}
        monkeypatch.setattr(module.time, "monotonic", lambda: clock["now"])

        for index in range(1200):
            limiter._allow(f"addr:{index}")
            clock["now"] += 0.001

        clock["now"] += 120.0
        limiter._allow("addr:fresh")

        assert len(limiter._callers) < 1200
