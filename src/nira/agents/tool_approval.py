"""Deciding whether a tool may run, with a person in the loop.

The approval queue, its REST endpoints, its permission memory and the
``approve`` scope on a paired device have all existed for phases. Nothing ever
put anything in the queue: the Claude Agent SDK was given no ``canUseTool``, so
an "ask" decision was terminal and a risky step was refused with nobody ever
offered the chance to say yes.

This is the piece in between. A request from the sidecar becomes a row in the
approval store; whoever is watching — the desktop UI, or a phone on the tailnet
holding the ``approve`` scope — answers it; the answer goes back down the pipe.

Two properties matter more than the plumbing:

*Fail closed.* Every path that is not an explicit approval denies. A timeout
denies, a crash denies, a store that will not open denies. The failure mode of
the opposite choice is running a destructive command because a database was
locked.

*Never block the event stream.* Waiting happens on its own thread, so progress
events keep flowing while the question is outstanding. A user deciding whether
to allow something needs to see what the agent did to get there.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from nira.core.events import EventType
from nira.tools.approval_store import (
    STATUS_APPROVED,
    STATUS_DENIED,
    STATUS_PENDING,
    TIER_HIGH,
    ApprovalStore,
)

logger = logging.getLogger(__name__)

__all__ = ["ApprovalBridge", "PermissionRequest", "permission_key_for"]

# How often to look for an answer. Short enough that a person tapping "allow"
# on a phone sees the run continue immediately, long enough not to spin.
_POLL_SECONDS = 0.4

# Tools that change the world rather than observe it. A permission key groups
# the ones a remembered decision should cover together, so "always allow reads"
# does not also mean "always allow shell commands".
_DESTRUCTIVE = frozenset({"Bash", "Write", "Edit", "NotebookEdit", "KillShell"})


def permission_key_for(tool: str, request_input: dict[str, Any]) -> str:
    """A stable key for remembering a decision about this kind of action.

    Deliberately coarse. Keying on the exact arguments would mean a remembered
    "always allow" never matched twice and the memory was decorative; keying on
    nothing but the tool would let one approval of ``Bash("ls")`` authorise
    every future shell command. Tool plus the first word of a command is the
    granularity a person can actually reason about.
    """
    tool = (tool or "").strip() or "unknown"
    if tool == "Bash":
        command = str(request_input.get("command", "")).strip()
        head = command.split()[0] if command else ""
        return f"tool:Bash:{head}" if head else "tool:Bash"
    return f"tool:{tool}"


@dataclass
class PermissionRequest:
    """One question from the sidecar: may this tool run?"""

    id: str
    tool: str
    input: dict[str, Any]
    title: str = ""
    display_name: str = ""
    description: str = ""
    reason: str = ""
    blocked_path: str = ""
    tool_use_id: str = ""

    @classmethod
    def from_event(cls, event: dict[str, Any]) -> "PermissionRequest":
        return cls(
            id=str(event.get("id", "")),
            tool=str(event.get("tool", "")),
            input=event.get("input") or {},
            title=str(event.get("title", "")),
            display_name=str(event.get("display_name", "")),
            description=str(event.get("description", "")),
            reason=str(event.get("reason", "")),
            blocked_path=str(event.get("blocked_path", "")),
            tool_use_id=str(event.get("tool_use_id", "")),
        )

    def summary(self) -> str:
        """One line a person can decide on without reading JSON.

        Prefers the sentence the SDK already rendered. Reconstructing one from
        the tool name and its arguments is a worse version of a string we were
        handed.
        """
        if self.title:
            return self.title
        if self.tool == "Bash":
            command = str(self.input.get("command", "")).strip()
            if command:
                return f"Run a shell command: {command}"
        target = self.blocked_path or self.input.get("file_path") or ""
        label = self.display_name or self.tool or "a tool"
        return f"{label}: {target}" if target else f"Use {label}"


class ApprovalBridge:
    """Turns sidecar permission requests into approval-queue rows and back.

    *send* writes one decision line to the sidecar's stdin. It is injected
    rather than reached for, because the writer has to be serialised against
    every other thread holding the same pipe.
    """

    def __init__(
        self,
        *,
        store: Optional[ApprovalStore],
        send: Callable[[dict[str, Any]], None],
        timeout_seconds: float = 300.0,
        bus: Any = None,
        agent_id: str = "",
        poll_seconds: float = _POLL_SECONDS,
    ) -> None:
        self._store = store
        self._send = send
        self._timeout = max(1.0, float(timeout_seconds))
        self._bus = bus
        self._agent_id = agent_id
        self._poll = max(0.05, float(poll_seconds))
        self._threads: list[threading.Thread] = []

    def handle(self, event: dict[str, Any]) -> None:
        """Start resolving one permission request. Returns immediately."""
        request = PermissionRequest.from_event(event)
        if not request.id:
            logger.debug("permission request with no id: %r", event)
            return
        worker = threading.Thread(
            target=self._resolve,
            args=(request,),
            name=f"nira-approval-{request.id}",
            daemon=True,
        )
        self._threads.append(worker)
        worker.start()

    def join(self, timeout: float = 5.0) -> None:
        """Wait for outstanding questions to settle, for orderly shutdown."""
        for worker in self._threads:
            worker.join(timeout=timeout)

    # ------------------------------------------------------------------

    def _resolve(self, request: PermissionRequest) -> None:
        try:
            decision, message = self._decide(request)
        except Exception:  # noqa: BLE001 - a broken approver must not allow
            logger.exception("approval failed for %s", request.tool)
            decision, message = False, "Nira could not ask for approval."
        self._reply(request, decision, message)

    def _decide(self, request: PermissionRequest) -> tuple[bool, str]:
        if self._store is None:
            # No queue means nobody can be asked. Denying is the same outcome
            # as the SDK's own behaviour without a canUseTool, and says why.
            return False, "No approval queue is configured on this desktop."

        key = permission_key_for(request.tool, request.input)

        remembered = self._store.get_permission(key)
        if remembered is not None and remembered.decision == "always_approve":
            self._announce(request, "approved", key, remembered=True)
            return True, ""
        if remembered is not None and remembered.decision == "always_deny":
            self._announce(request, "denied", key, remembered=True)
            return False, "You have always denied this."

        action = self._store.queue_action(
            action_type=f"tool:{request.tool}",
            description=request.summary(),
            payload={
                "tool": request.tool,
                "input": request.input,
                "reason": request.reason,
                "blocked_path": request.blocked_path,
                "tool_use_id": request.tool_use_id,
                "agent": self._agent_id,
            },
            permission_key=key,
            # A tool that changes the world is never auto-remembered from a
            # single yes; reading something is.
            tier=TIER_HIGH if request.tool in _DESTRUCTIVE else "medium",
            # Hours are the queue's unit, and this question dies with the run
            # that asked it — a decision made tomorrow reaches nothing.
            ttl_hours=1,
        )
        self._publish(
            EventType.APPROVAL_REQUESTED,
            {
                "id": action.id,
                "request_id": request.id,
                "tool": request.tool,
                "description": action.description,
                "permission_key": key,
                "tier": action.tier,
                "agent": self._agent_id,
                "expires_in": self._timeout,
            },
        )

        approved = self._await_decision(action.id)
        self._announce(request, "approved" if approved else "denied", key)
        if approved:
            return True, ""
        return False, "Refused."

    def _await_decision(self, action_id: str) -> bool:
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            action = self._store.get_action(action_id)
            if action is None:
                # The row vanished. Treat an answer we cannot read as no.
                return False
            if action.status == STATUS_APPROVED:
                return True
            if action.status != STATUS_PENDING:
                return False
            time.sleep(self._poll)

        # Nobody answered. Mark it so the queue does not keep offering a
        # question whose run has already moved on without it.
        try:
            self._store.update_status(action_id, STATUS_DENIED)
        except Exception:  # noqa: BLE001 - bookkeeping, not the decision
            logger.debug("could not expire approval %s", action_id, exc_info=True)
        return False

    def _reply(self, request: PermissionRequest, approved: bool, message: str) -> None:
        payload: dict[str, Any] = {
            "type": "decision",
            "id": request.id,
            "behavior": "allow" if approved else "deny",
        }
        if not approved:
            payload["message"] = message or "Refused."
        try:
            self._send(payload)
        except Exception:  # noqa: BLE001 - the sidecar may already be gone
            logger.debug("could not deliver decision for %s", request.id, exc_info=True)

    def _announce(
        self,
        request: PermissionRequest,
        outcome: str,
        key: str,
        *,
        remembered: bool = False,
    ) -> None:
        self._publish(
            EventType.APPROVAL_DECIDED,
            {
                "request_id": request.id,
                "tool": request.tool,
                "outcome": outcome,
                "permission_key": key,
                "remembered": remembered,
                "agent": self._agent_id,
            },
        )

    def _publish(self, event_type: EventType, data: dict[str, Any]) -> None:
        if self._bus is None:
            return
        try:
            self._bus.publish(event_type, data)
        except Exception:  # noqa: BLE001 - telemetry never fails a decision
            logger.debug("could not publish %s", event_type, exc_info=True)


def encode_decision(payload: dict[str, Any]) -> str:
    """One NDJSON line for the sidecar's stdin."""
    return json.dumps(payload, separators=(",", ":")) + "\n"
