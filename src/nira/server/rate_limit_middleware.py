"""Per-caller HTTP request rate limiting.

The existing limiter gates *tool calls* — it asks whether an agent may run a
particular tool. Nothing gated HTTP requests themselves, so a caller holding a
valid key could issue completions as fast as the machine would accept them, and
an unauthenticated flood of a public path cost a connection each with no
ceiling at all.

That was survivable while the server only ever listened on loopback. Once it
binds to a tailnet — shared with devices, and possibly with accounts that are
not yours — the absence of a request ceiling is the difference between one
misbehaving client and an unusable machine.

Keyed per device where a device is known, so one phone in a retry loop cannot
consume the budget of every other paired client.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Deque, Dict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Generous for a human at a keyboard or a phone streaming a reply, low enough
# that a runaway loop is stopped rather than merely slowed.
DEFAULT_REQUESTS_PER_MINUTE = 240

# Paths that must stay answerable even when a caller is being throttled.
# /health is what a supervisor uses to decide the process is alive; rate
# limiting it turns a busy server into one that looks dead and gets restarted.
_EXEMPT_PREFIXES = ("/health",)


class _SlidingWindow:
    """Request timestamps for one caller, within the trailing minute."""

    __slots__ = ("hits",)

    def __init__(self) -> None:
        self.hits: Deque[float] = deque()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Reject a caller that exceeds *requests_per_minute*.

    A sliding window rather than a fixed one: fixed windows let a caller send
    a full budget at 59s and another at 61s, which is twice the intended rate
    at exactly the moment a retry storm produces it.
    """

    def __init__(
        self,
        app,  # noqa: ANN001
        requests_per_minute: int = DEFAULT_REQUESTS_PER_MINUTE,
    ) -> None:
        super().__init__(app)
        self._limit = max(1, requests_per_minute)
        self._callers: Dict[str, _SlidingWindow] = {}
        self._lock = threading.Lock()

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        if request.url.path.startswith(_EXEMPT_PREFIXES):
            return await call_next(request)

        key = self._caller_key(request)
        allowed, retry_after = self._allow(key)
        if not allowed:
            logger.warning("Rate limit exceeded for %s", key)
            return JSONResponse(
                {"detail": "Too many requests"},
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)

    @staticmethod
    def _caller_key(request: Request) -> str:
        """Identify the caller as narrowly as the request allows.

        A paired device is its own bucket, so one phone stuck in a retry loop
        cannot exhaust the budget of every other client. Falling back to the
        peer address keeps unauthenticated traffic bounded too.
        """
        device = request.scope.get("nira_device")
        if device is not None:
            return f"device:{getattr(device, 'id', 'unknown')}"
        client = request.client
        return f"addr:{client.host}" if client else "addr:unknown"

    def _allow(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - 60.0
        with self._lock:
            window = self._callers.get(key)
            if window is None:
                window = _SlidingWindow()
                self._callers[key] = window
            hits = window.hits
            while hits and hits[0] < cutoff:
                hits.popleft()
            if len(hits) >= self._limit:
                # Seconds until the oldest hit ages out, so a client told to
                # retry actually can.
                retry_after = max(1, int(hits[0] - cutoff) + 1)
                return False, retry_after
            hits.append(now)

            # Callers that have gone quiet leave empty windows behind. Sweep
            # occasionally so a long-lived server does not accumulate one
            # entry per address it has ever seen.
            if len(self._callers) > 1024:
                self._prune_locked(cutoff)
            return True, 0

    def _prune_locked(self, cutoff: float) -> None:
        stale = [
            key
            for key, window in self._callers.items()
            if not window.hits or window.hits[-1] < cutoff
        ]
        for key in stale:
            del self._callers[key]


__all__ = ["DEFAULT_REQUESTS_PER_MINUTE", "RateLimitMiddleware"]
