"""Starting work on a project, from anywhere.

`nira project add` has registered directories since Phase 4, and
:class:`~nira.agents.claude_code.ClaudeCodeAgent` has taken a ``workspace``
since it existed — but nothing connected the two over HTTP, so the registry was
reachable only from a shell on the machine itself. A phone could chat with the
model and watch agents work; it could not say "work on this project", which is
the thing the phone is for.

A run is started, not awaited. Agentic work on a real repository takes minutes,
and an HTTP request that blocks for minutes is a request that a phone's radio
drops halfway through. The response carries a run id; progress arrives on the
event socket the client is already watching.
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

projects_router = APIRouter(prefix="/v1/projects", tags=["projects"])

# Keep a bounded history. A phone that reconnects wants to know how the run it
# started turned out; it does not want every run since the server booted, and
# an unbounded dict is a leak in a process meant to stay up for weeks.
_MAX_RUNS = 100


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ProjectRun:
    """One agent run against one project."""

    id: str
    project_id: str
    project_name: str
    prompt: str
    status: str = "running"
    started_at: str = field(default_factory=_now)
    finished_at: str = ""
    result: str = ""
    error: str = ""
    turns: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "prompt": self.prompt,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "error": self.error,
            "turns": self.turns,
        }


class RunRegistry:
    """In-memory record of runs started through the API.

    Deliberately not persisted. A run cannot outlive the process that spawned
    the subprocess doing the work, so a record surviving a restart would
    describe a run that is no longer happening — worse than no record at all.
    """

    def __init__(self, limit: int = _MAX_RUNS) -> None:
        self._runs: Dict[str, ProjectRun] = {}
        self._order: List[str] = []
        self._limit = limit
        self._lock = threading.Lock()

    def add(self, run: ProjectRun) -> None:
        with self._lock:
            self._runs[run.id] = run
            self._order.append(run.id)
            while len(self._order) > self._limit:
                evicted = self._order.pop(0)
                self._runs.pop(evicted, None)

    def get(self, run_id: str) -> Optional[ProjectRun]:
        with self._lock:
            return self._runs.get(run_id)

    def list(self, project_id: str = "") -> List[ProjectRun]:
        with self._lock:
            runs = [self._runs[key] for key in reversed(self._order)]
        if project_id:
            runs = [run for run in runs if run.project_id == project_id]
        return runs

    def finish(
        self,
        run_id: str,
        *,
        status: str,
        result: str = "",
        error: str = "",
        turns: int = 0,
    ) -> None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            run.status = status
            run.result = result
            run.error = error
            run.turns = turns
            run.finished_at = _now()


def _registry(request: Request) -> RunRegistry:
    existing = getattr(request.app.state, "project_runs", None)
    if existing is None:
        existing = RunRegistry()
        request.app.state.project_runs = existing
    return existing


def _store(request: Request):  # noqa: ANN202
    store = getattr(request.app.state, "project_store", None)
    if store is not None:
        return store
    try:
        from nira.core.paths import get_config_dir
        from nira.projects import ProjectStore

        store = ProjectStore(get_config_dir() / "projects.db")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Project registry unavailable: %s", exc)
        raise HTTPException(
            status_code=501, detail="Project registry unavailable on this desktop."
        ) from exc
    request.app.state.project_store = store
    return store


@projects_router.get("")
@projects_router.get("/")
async def list_projects(request: Request) -> Dict[str, Any]:
    """Every registered project, so a client can offer a picker."""
    store = _store(request)
    return {"projects": [project.to_dict() for project in store.list()]}


# Registered before "/{reference}" on purpose: a single-segment route declared
# first would swallow "/runs" and look up a project called "runs".
@projects_router.get("/runs")
async def list_runs(request: Request) -> Dict[str, Any]:
    """Recent runs, newest first."""
    project_id = request.query_params.get("project_id", "")
    return {"runs": [run.to_dict() for run in _registry(request).list(project_id)]}


@projects_router.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request) -> Dict[str, Any]:
    run = _registry(request).get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="No such run")
    return run.to_dict()


@projects_router.get("/{reference}")
async def get_project(reference: str, request: Request) -> Dict[str, Any]:
    store = _store(request)
    project = store.resolve(reference)
    if project is None:
        raise HTTPException(status_code=404, detail=f"No project matches {reference!r}")
    return project.to_dict()


@projects_router.post("/{reference}/run")
async def run_project(reference: str, request: Request) -> Dict[str, Any]:
    """Start agentic work in a project's directory.

    Returns as soon as the work is under way. The run id identifies it in
    ``/v1/projects/runs``; the progress itself is on ``/v1/agents/events``,
    which every client watching this desktop is already subscribed to.
    """
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Expected a JSON body") from exc

    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Missing 'prompt'")

    store = _store(request)
    project = store.resolve(reference)
    if project is None:
        raise HTTPException(status_code=404, detail=f"No project matches {reference!r}")

    from pathlib import Path

    workspace = Path(project.path).expanduser()
    if not workspace.is_dir():
        # A project whose directory has moved would otherwise fail deep inside
        # the Node subprocess, where the reason never reaches the caller.
        raise HTTPException(
            status_code=409,
            detail=(
                f"{project.name} points at {project.path}, which is not a directory."
            ),
        )

    run = ProjectRun(
        id=f"run_{uuid.uuid4().hex[:12]}",
        project_id=project.id,
        project_name=project.name,
        prompt=prompt,
    )
    registry = _registry(request)
    registry.add(run)

    agent = _build_agent(request, project, body)
    if agent is None:
        registry.finish(
            run.id, status="error", error="No agent is configured on this desktop."
        )
        raise HTTPException(
            status_code=501, detail="No agent is configured on this desktop."
        )

    def _work() -> None:
        try:
            result = agent.run(prompt)
        except Exception as exc:  # noqa: BLE001 - a failed run is a result
            logger.exception("project run failed")
            registry.finish(run.id, status="error", error=str(exc))
            return
        metadata = getattr(result, "metadata", {}) or {}
        failed = bool(metadata.get("error"))
        registry.finish(
            run.id,
            status="error" if failed else "done",
            result=getattr(result, "content", "") or "",
            error=str(metadata.get("error_type") or "") if failed else "",
            turns=getattr(result, "turns", 0) or 0,
        )

    # A daemon thread, so a run still in flight cannot hold the server open on
    # shutdown. The work itself is a subprocess that the OS reaps with us.
    threading.Thread(target=_work, name=f"project-run-{run.id}", daemon=True).start()

    return {"run": run.to_dict()}


def _build_agent(request: Request, project, body: Dict[str, Any]):  # noqa: ANN001, ANN202
    """Construct an agent rooted in the project's directory.

    The workspace is the whole point: the desktop's own agent is rooted
    wherever the server was started, so reusing it would run the work in the
    wrong tree — silently, and with file and shell access.
    """
    from nira.agents.claude_code import ClaudeCodeAgent

    state = request.app.state
    engine = getattr(state, "engine", None)
    config = getattr(state, "config", None)
    if engine is None:
        return None

    model = ""
    if config is not None:
        model = getattr(getattr(config, "model", None), "name", "") or ""

    # Bounded, and not taken from the request. A device holding only "ask"
    # must not be able to name its own permission mode — that is how a phone
    # that was granted the ability to start work grants itself the ability to
    # skip every approval the desktop would otherwise raise. The ceilings are
    # clamped for the same reason: a caller should not be able to pin a Node
    # subprocess open for a day.
    timeout = _clamp(body.get("timeout"), default=1800, low=30, high=7200)
    max_turns = _clamp(body.get("max_turns"), default=60, low=1, high=200)
    permission_mode = ""
    if config is not None:
        permission_mode = (
            getattr(getattr(config, "agent", None), "permission_mode", "") or ""
        )

    try:
        return ClaudeCodeAgent(
            engine,
            model,
            bus=getattr(state, "bus", None),
            workspace=str(project.path),
            timeout=timeout,
            max_turns=max_turns,
            permission_mode=permission_mode,
        )
    except Exception:  # noqa: BLE001
        logger.exception("could not build the project agent")
        return None


def _clamp(value: Any, *, default: int, low: int, high: int) -> int:
    """Read an integer from a request body, bounded and never raising."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


__all__ = ["projects_router", "ProjectRun", "RunRegistry"]
