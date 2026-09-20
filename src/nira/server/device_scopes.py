"""What a paired device is allowed to do.

A device key is not the machine key. The machine key belongs to whoever is
sitting at the computer; a device key lives on a phone that can be lost,
borrowed, or left unlocked on a table. :mod:`nira.devices.store` has issued
scopes since devices existed, and :class:`~nira.server.auth_middleware.AuthMiddleware`
has attached them to every request — but nothing read them, so a phone paired
with ``ask`` and ``watch`` could still rewrite config and manage other
devices. This module is the part that reads them.

The rule is default-deny: a path that has not been classified is refused to
devices, not allowed. The alternative fails open, and fails open precisely on
the routes nobody thought about — which is where the damage is.

The machine key is unaffected. It has no device identity attached, so the
desktop UI and the CLI never reach this code.
"""

from __future__ import annotations

from nira.devices.store import SCOPE_ADMIN, SCOPE_APPROVE, SCOPE_ASK, SCOPE_WATCH

__all__ = ["required_scope", "ADMIN_ONLY", "NO_SCOPE"]

# Returned for paths any authenticated device may reach, whatever it was
# granted. Only one so far: a device asking what it is. A client learns which
# controls to show from its own scope list, so gating that behind a scope
# leaves a narrowly-paired device unable to discover it is narrowly paired.
NO_SCOPE = ""

# Reaching any of these is administering the desktop, not using it. A phone
# gets here only when it was deliberately paired with ``admin``.
ADMIN_ONLY = (
    "/v1/devices",  # issuing and revoking other devices' access
    "/v1/config",
    "/v1/vault",
    "/v1/connectors",
    "/v1/gateway",
    "/v1/auth",
    "/v1/telemetry",
    "/v1/analytics",
    "/v1/budget",
    "/v1/optimize",
    "/v1/learning",
    "/metrics",
    "/api/digest",
)

# Sending work to the desktop.
_ASK_PATHS = (
    "/v1/chat/completions",
    "/v1/speech/transcribe",
    "/v1/completions",
    "/v1/responses",
)

# Reading what the desktop is doing. Everything here must be side-effect free,
# which is why the method is checked too rather than trusting the prefix.
_WATCH_PATHS = (
    "/v1/info",
    "/v1/models",
    "/v1/agents",
    "/v1/managed-agents",
    "/v1/sessions",
    "/v1/traces",
    "/v1/projects",
    "/v1/skills",
    "/v1/tools",
    "/v1/memory",
    "/v1/speech/health",
)

# Authentication alone is enough here.
_SELF_PATHS = ("/v1/devices/me",)

_APPROVE_PREFIX = "/v1/approvals"


def _matches(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in prefixes)


def required_scope(method: str, path: str) -> str:
    """Return the scope a device needs for ``method path``.

    Returns :data:`NO_SCOPE` for the handful of paths any authenticated device
    may reach. Otherwise never returns nothing: an unclassified path requires
    :data:`SCOPE_ADMIN`, so adding a route without thinking about phones locks
    it down rather than opening it up.
    """
    path = path.rstrip("/") or "/"
    verb = method.upper()

    # Checked first: ``/v1/devices/me`` sits under the ``/v1/devices`` admin
    # prefix that would otherwise cover it.
    if _matches(path, _SELF_PATHS):
        return NO_SCOPE

    if _matches(path, _WATCH_PATHS) and verb in ("GET", "HEAD", "OPTIONS"):
        return SCOPE_WATCH

    if path.startswith(_APPROVE_PREFIX):
        # Listing what is waiting is part of answering it; a phone that can
        # approve but cannot see the queue can only guess.
        return SCOPE_APPROVE

    if _matches(path, _ASK_PATHS):
        return SCOPE_ASK

    if _matches(path, ADMIN_ONLY):
        return SCOPE_ADMIN

    # A POST to something otherwise watchable — starting an agent, opening a
    # session — is asking the desktop to do work, not reading it.
    #
    # Deleting or replacing is neither. A phone granted "ask" was granted the
    # ability to make the desktop work, not to destroy what is already there,
    # so the destructive verbs fall through to admin with everything else.
    if _matches(path, _WATCH_PATHS) and verb == "POST":
        return SCOPE_ASK

    return SCOPE_ADMIN
