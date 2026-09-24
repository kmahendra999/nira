"""REST endpoints for the proactive-agent approval queue."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from nira.tools.approval_store import (
    DECISION_ALWAYS_APPROVE,
    DECISION_ALWAYS_DENY,
    STATUS_APPROVED,
    STATUS_DENIED,
    TIER_LOW,
    TIER_MEDIUM,
    TIER_TRIVIAL,
    ApprovalStore,
    PendingAction,
)

try:
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel
except ImportError:
    raise ImportError("fastapi is required for approval routes")

logger = logging.getLogger(__name__)

router = APIRouter()

# Singleton that shares the same DB file as ProactiveAgent (WAL mode is safe)
_store: Optional[ApprovalStore] = None


def _get_store() -> ApprovalStore:
    global _store
    if _store is None:
        _store = ApprovalStore()
    return _store


# Which tiers may be remembered from a single answer. `high` is excluded
# deliberately: the bridge assigns it to anything that changes the world, and
# one yes on a phone should not stand in for every future yes to `rm`.
_REMEMBERABLE = (TIER_TRIVIAL, TIER_LOW, TIER_MEDIUM)


class Decision(BaseModel):
    """Body for approve/deny. Absent body means "just this once"."""

    remember: bool = False


def _serialize(action: PendingAction) -> Dict[str, Any]:
    return {
        "id": action.id,
        "action_type": action.action_type,
        "description": action.description,
        "payload": action.payload,
        "permission_key": action.permission_key,
        "tier": action.tier,
        "status": action.status,
        "created_at": action.created_at,
        "expires_at": action.expires_at,
        # So a client knows whether to offer "always allow" at all, rather
        # than showing a control that the server will silently ignore.
        "can_remember": action.tier in _REMEMBERABLE,
    }


def _remember(store: ApprovalStore, action: PendingAction, decision: str) -> bool:
    """Record a standing answer, when the tier allows one.

    The gate is here and not in the store: `set_permission` takes no tier and
    so enforces no policy of its own.
    """
    if action.tier not in _REMEMBERABLE:
        return False
    store.set_permission(
        action.permission_key,
        decision,
        approved=decision == DECISION_ALWAYS_APPROVE,
    )
    return True


@router.get("/v1/approvals/pending")
async def list_pending_approvals() -> Dict[str, Any]:
    store = _get_store()
    store.expire_stale()
    actions = store.list_pending()
    return {"actions": [_serialize(a) for a in actions], "count": len(actions)}


@router.post("/v1/approvals/{action_id}/approve")
async def approve_action(
    action_id: str, decision: Decision | None = None
) -> Dict[str, Any]:
    """Approve once, or -- with ``{"remember": true}`` -- from now on.

    The store has held `always_approve` since the permission memory existed
    and the bridge has honoured it, short-circuiting before anyone is asked.
    No client could set it, so the memory was reachable only by editing the
    database by hand.
    """
    store = _get_store()
    action = store.get_action(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Action not found")
    store.update_status(action_id, STATUS_APPROVED)
    remembered = bool(decision and decision.remember) and _remember(
        store, action, DECISION_ALWAYS_APPROVE
    )
    logger.info("Action %s approved via UI (remembered=%s)", action_id, remembered)
    return {"status": "approved", "id": action_id, "remembered": remembered}


@router.post("/v1/approvals/{action_id}/deny")
async def deny_action(
    action_id: str, decision: Decision | None = None
) -> Dict[str, Any]:
    """Deny once, or -- with ``{"remember": true}`` -- from now on."""
    store = _get_store()
    action = store.get_action(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Action not found")
    store.update_status(action_id, STATUS_DENIED)
    remembered = bool(decision and decision.remember) and _remember(
        store, action, DECISION_ALWAYS_DENY
    )
    logger.info("Action %s denied via UI (remembered=%s)", action_id, remembered)
    return {"status": "denied", "id": action_id, "remembered": remembered}


__all__ = ["router"]
