"""ClaudeCodeAgent -- wraps the Claude Agent SDK via Node.js subprocess bridge.

Spawns a Node.js runner process that calls the
``@anthropic-ai/claude-agent-sdk`` package, communicating via JSON over
stdin/stdout with sentinel-delimited output.

The engine parameter is accepted for interface conformance with BaseAgent but
is not used -- inference is handled entirely by the Claude Agent SDK.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, List, Optional

from nira.agents._stubs import AgentContext, AgentResult, BaseAgent
from nira.agents.tool_approval import encode_decision
from nira.core.events import EventBus, EventType
from nira.core.paths import get_config_dir
from nira.core.registry import AgentRegistry
from nira.core.types import ToolResult
from nira.engine._stubs import InferenceEngine

logger = logging.getLogger(__name__)

# Sentinel markers for parsing subprocess output
_OUTPUT_START = "---NIRA_OUTPUT_START---"
_OUTPUT_END = "---NIRA_OUTPUT_END---"

# Prefix on each streamed progress line. Must match EVENT_PREFIX in index.mjs.
_EVENT_PREFIX = "---NIRA_EVENT---"

# Path to the bundled runner source (relative to this module).
# In editable installs this lives next to this file; in wheel installs
# it is placed under _node_modules/ to avoid namespace package conflicts.
_RUNNER_SRC = Path(__file__).resolve().parent / "claude_code_runner"
if not _RUNNER_SRC.exists():
    _RUNNER_SRC = (
        Path(__file__).resolve().parents[2] / "_node_modules" / "claude_code_runner"
    )


@AgentRegistry.register("claude_code")
class ClaudeCodeAgent(BaseAgent):
    """Agent that wraps the Claude Agent SDK via a Node.js subprocess.

    Spawns a Node.js process running ``index.mjs`` which imports
    ``@anthropic-ai/claude-agent-sdk`` and streams agentic responses.  Results
    are communicated back via sentinel-delimited JSON on stdout.

    The ``engine`` parameter is accepted for BaseAgent interface conformance
    but is not used -- all inference is handled by the Claude Agent SDK.
    """

    agent_id = "claude_code"
    accepts_tools = False
    required_capabilities = ("code:execute", "file:read", "file:write")
    _default_temperature = 0.7
    _default_max_tokens = 1024

    def __init__(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        bus: Optional[EventBus] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        api_key: str = "",
        workspace: str = "",
        session_id: str = "",
        allowed_tools: Optional[List[str]] = None,
        system_prompt: str = "",
        timeout: int = 300,
        max_turns: int = 30,
        permission_mode: str = "",
        ask_permission: bool = True,
        approval_timeout: float = 300.0,
        approval_store: Optional[Any] = None,
        capability_policy: Optional[Any] = None,
        rate_limiter: Optional[Any] = None,
        agent_id: Optional[str] = None,
    ) -> None:
        super().__init__(
            engine,
            model,
            bus=bus,
            temperature=temperature,
            max_tokens=max_tokens,
            capability_policy=capability_policy,
            rate_limiter=rate_limiter,
            agent_id=agent_id,
        )
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._workspace = workspace or os.getcwd()
        self._session_id = session_id
        self._allowed_tools = allowed_tools
        self._system_prompt = system_prompt
        self._timeout = timeout
        # Both were previously fixed inside the runner and unreachable from
        # here: 30 turns is low for "work on this project until it is done",
        # and no permission mode was set at all, so the posture for an agent
        # with file and shell access was whatever the SDK happened to default
        # to rather than something Nira chose.
        self._max_turns = max_turns
        self._permission_mode = permission_mode
        # Route "may this run?" back to a person instead of letting the SDK
        # decide alone. On by default because the alternative is what happened
        # before: with no canUseTool the SDK treats an ask as terminal, so a
        # risky step was refused outright and nobody was ever offered the
        # chance to say yes. Enabling it can only widen what is possible — a
        # timeout still denies, which is exactly the old behaviour.
        self._ask_permission = ask_permission
        self._approval_timeout = approval_timeout
        self._approval_store = approval_store
        self._node_executable = "node"

    # ------------------------------------------------------------------
    # Runner management
    # ------------------------------------------------------------------

    def _ensure_runner(self) -> Path:
        """Copy the bundled runner to ``~/.nira/claude_code_runner/``
        and install the Agent SDK when it is missing or outdated.

        Returns the path to the runner directory.

        Raises :class:`RuntimeError` if Node.js or npm is not available.
        """
        node_path = shutil.which("node")
        if node_path is None:
            raise RuntimeError(
                "ClaudeCodeAgent requires Node.js (>=22). "
                "Install it from https://nodejs.org/ or via your package manager."
            )
        npm_path = shutil.which("npm")
        if npm_path is None:
            raise RuntimeError(
                "ClaudeCodeAgent requires npm. Install Node.js (>=22) with npm."
            )
        self._node_executable = node_path

        dest = get_config_dir() / "claude_code_runner"
        dest.mkdir(parents=True, exist_ok=True)

        for name in ("package.json", "index.mjs"):
            shutil.copy2(_RUNNER_SRC / name, dest / name)

        package = json.loads((dest / "package.json").read_text(encoding="utf-8"))
        expected_sdk = package["dependencies"]["@anthropic-ai/claude-agent-sdk"]
        installed_package = (
            dest
            / "node_modules"
            / "@anthropic-ai"
            / "claude-agent-sdk"
            / "package.json"
        )
        try:
            installed_sdk = json.loads(
                installed_package.read_text(encoding="utf-8")
            ).get("version")
        except (OSError, json.JSONDecodeError):
            installed_sdk = None

        # Existing caches contain the old CLI-only package, so validate the
        # installed SDK instead of trusting that node_modules merely exists.
        if installed_sdk != expected_sdk:
            logger.info("Installing claude_code_runner dependencies...")
            subprocess.run(
                [npm_path, "install", "--omit=dev", "--include=optional"],
                cwd=str(dest),
                check=True,
                capture_output=True,
                timeout=120,
            )

        return dest

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        """Execute a query via the Claude Agent SDK subprocess.

        Spawns ``node index.mjs``, writes a JSON request to stdin, and
        reads sentinel-delimited JSON output from stdout.
        """
        denied = self._execution_denied_result()
        if denied is not None:
            return denied
        self._emit_turn_start(input)

        runner_dir = self._ensure_runner()

        # Build the request payload
        request = {
            "prompt": input,
            "api_key": self._api_key,
            "workspace": self._workspace,
            "allowed_tools": self._allowed_tools or [],
            "system_prompt": self._system_prompt,
            "session_id": self._session_id,
            "max_turns": self._max_turns,
            "permission_mode": self._permission_mode,
            "ask_permission": bool(self._ask_permission),
        }

        try:
            stdout, stderr, returncode = self._run_streaming(runner_dir, request)
        except subprocess.TimeoutExpired:
            self._emit_turn_end(turns=1, error=True)
            return AgentResult(
                content=f"Claude Code agent timed out after {self._timeout}s.",
                turns=1,
                metadata={"error": True, "error_type": "timeout"},
            )

        if returncode != 0:
            stderr = stderr.strip() if stderr else "Unknown error"
            logger.error(
                "claude_code_runner exited with code %d: %s",
                returncode,
                stderr,
            )
            self._emit_turn_end(turns=1, error=True)
            return AgentResult(
                content=f"Claude Code agent failed: {stderr}",
                turns=1,
                metadata={"error": True, "returncode": returncode},
            )

        # Parse sentinel-delimited output
        content, tool_results, metadata = self._parse_output(stdout)

        # Remember the SDK's own session id so the next run can resume it.
        session_id = metadata.get("session_id")
        if session_id:
            self._session_id = session_id

        turns = int(metadata.get("turns") or 1)
        self._emit_turn_end(turns=turns)
        return AgentResult(
            content=content,
            tool_results=tool_results,
            turns=turns,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Streaming subprocess
    # ------------------------------------------------------------------

    def _run_streaming(
        self,
        runner_dir: Any,
        request: dict[str, Any],
    ) -> tuple[str, str, int]:
        """Run the sidecar, republishing its events as they arrive.

        ``subprocess.run(capture_output=True)`` buffers until the process
        exits, so a long agentic run produced total silence and then one blob.
        The sidecar already streams a line per SDK message and Nira already has
        an event bus wired to an authenticated WebSocket and a live trace UI;
        this is the missing link between them.

        stdout is read on a worker thread and handed over a queue so the
        timeout stays enforceable — a blocking readline gives no way to notice
        a deadline passing.
        """
        proc = subprocess.Popen(
            [self._node_executable, "index.mjs"],
            cwd=str(runner_dir),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # line buffered, or events arrive in 8 KB clumps
        )

        lines: "queue.Queue[str | None]" = queue.Queue()

        def _pump() -> None:
            try:
                assert proc.stdout is not None
                for line in proc.stdout:
                    lines.put(line)
            finally:
                lines.put(None)

        reader = threading.Thread(target=_pump, name="nira-claude-stdout", daemon=True)
        reader.start()

        # stdin stays open. Asking whether a tool may run means the answer
        # arrives after the request did, so the pipe has to carry a
        # conversation rather than one write and a close.
        stdin_lock = threading.Lock()

        def _send(payload: dict[str, Any]) -> None:
            with stdin_lock:
                if proc.stdin is None or proc.stdin.closed:
                    return
                proc.stdin.write(encode_decision(payload))
                proc.stdin.flush()

        try:
            assert proc.stdin is not None
            with stdin_lock:
                proc.stdin.write(json.dumps(request) + "\n")
                proc.stdin.flush()
        except (BrokenPipeError, ValueError):
            pass  # the process died early; the exit code below reports it

        bridge = self._build_approval_bridge(_send)

        collected: list[str] = []
        deadline = time.monotonic() + self._timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                proc.kill()
                raise subprocess.TimeoutExpired(
                    cmd=self._node_executable, timeout=self._timeout
                )
            try:
                line = lines.get(timeout=min(remaining, 1.0))
            except queue.Empty:
                continue
            if line is None:
                break
            if line.startswith(_EVENT_PREFIX):
                payload = line[len(_EVENT_PREFIX) :]
                if bridge is not None:
                    self._route_permission(payload, bridge)
                self._publish_runner_event(payload)
            else:
                collected.append(line)

        # Nothing more will be asked; let the sidecar see end-of-input so it
        # does not sit waiting on a pipe that will never speak again.
        with stdin_lock:
            if proc.stdin is not None and not proc.stdin.closed:
                try:
                    proc.stdin.close()
                except (BrokenPipeError, ValueError):
                    pass
        if bridge is not None:
            bridge.join(timeout=1.0)

        try:
            proc.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            proc.kill()
            raise

        stderr = ""
        if proc.stderr is not None:
            try:
                stderr = proc.stderr.read()
            finally:
                proc.stderr.close()

        return "".join(collected), stderr, proc.returncode or 0

    def _build_approval_bridge(self, send: Any) -> Any:
        """An approval bridge, or None when this run is not asking.

        Returns None rather than a disabled bridge so the hot loop can skip the
        JSON parse entirely for runs that never ask anything.
        """
        if not self._ask_permission:
            return None
        from nira.agents.tool_approval import ApprovalBridge

        store = self._approval_store
        if store is None:
            try:
                from nira.tools.approval_store import ApprovalStore

                store = ApprovalStore()
            except Exception:  # noqa: BLE001 - no queue means deny, not crash
                logger.warning(
                    "approval queue unavailable; risky tools will be refused"
                )
                store = None
        return ApprovalBridge(
            store=store,
            send=send,
            timeout_seconds=self._approval_timeout,
            bus=self._bus,
            agent_id=self.agent_id,
        )

    @staticmethod
    def _route_permission(payload: str, bridge: Any) -> None:
        """Hand a permission request to the bridge; ignore everything else."""
        try:
            event = json.loads(payload)
        except (ValueError, TypeError):
            return
        if event.get("type") == "permission_request":
            bridge.handle(event)

    def _publish_runner_event(self, payload: str) -> None:
        """Republish one sidecar event on the shared event bus.

        Mapped onto the event types the WebSocket bridge already forwards and
        the trace UI already renders, so live progress needs no UI change at
        all. A malformed line is dropped: telemetry must not take down the run
        it is reporting on.
        """
        if not self._bus:
            return
        try:
            event = json.loads(payload)
        except (ValueError, TypeError):
            logger.debug("unparseable runner event: %r", payload[:200])
            return

        kind = event.get("type")
        if kind == "tool_start":
            self._bus.publish(
                EventType.TOOL_CALL_START,
                {
                    "tool": event.get("tool", ""),
                    "arguments": event.get("input", {}),
                    "agent": self.agent_id,
                },
            )
        elif kind == "tool_end":
            self._bus.publish(
                EventType.TOOL_CALL_END,
                {
                    "tool": event.get("tool", ""),
                    "success": bool(event.get("success", True)),
                    "result": event.get("result", ""),
                    "latency": 0.0,
                    "metadata": {},
                    "agent": self.agent_id,
                },
            )
        elif kind == "text":
            self._bus.publish(
                EventType.INFERENCE_END,
                {"agent": self.agent_id, "content": event.get("text", "")},
            )

    # ------------------------------------------------------------------
    # Output parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_output(
        stdout: str,
    ) -> tuple[str, list[ToolResult], dict[str, Any]]:
        """Extract the sentinel-wrapped JSON from subprocess stdout.

        Returns ``(content, tool_results, metadata)``.
        """
        start = stdout.find(_OUTPUT_START)
        end = stdout.find(_OUTPUT_END)

        if start == -1 or end == -1:
            # No sentinels -- treat entire stdout as plain content
            return stdout.strip(), [], {}

        json_str = stdout[start + len(_OUTPUT_START) : end].strip()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return stdout.strip(), [], {"parse_error": True}

        content = data.get("content", "")
        raw_tools = data.get("tool_results", [])
        metadata = data.get("metadata", {})

        tool_results = [
            ToolResult(
                tool_name=tr.get("tool_name", "unknown"),
                content=tr.get("content", ""),
                success=tr.get("success", True),
            )
            for tr in raw_tools
        ]

        return content, tool_results, metadata


__all__ = ["ClaudeCodeAgent"]
