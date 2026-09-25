"""Extended API routes for agents, workflows, memory, traces, etc."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import (
    APIRouter,
    File,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---- Request/Response models ----


class AgentCreateRequest(BaseModel):
    agent_type: str
    tools: Optional[List[str]] = None
    agent_id: Optional[str] = None


class AgentMessageRequest(BaseModel):
    message: str


class MemoryStoreRequest(BaseModel):
    content: str
    metadata: Optional[Dict[str, Any]] = None


class MemorySearchRequest(BaseModel):
    query: str
    top_k: int = 5


class MemoryIndexRequest(BaseModel):
    path: str


class MemoryConfigRequest(BaseModel):
    """Memory settings the UI can change and expect to survive a restart.

    Every field is optional: the UI sends only what the user touched, and an
    omitted field is left at whatever the config file already says.
    """

    enabled: Optional[bool] = None
    context_from_memory: Optional[bool] = None
    context_top_k: Optional[int] = None
    context_min_score: Optional[float] = None
    context_max_tokens: Optional[int] = None
    default_backend: Optional[str] = None


class BudgetLimitsRequest(BaseModel):
    max_tokens_per_day: Optional[int] = None
    max_requests_per_hour: Optional[int] = None


class FeedbackScoreRequest(BaseModel):
    trace_id: str
    score: float
    source: str = "api"


class OptimizeRunRequest(BaseModel):
    benchmark: str
    max_trials: int = 20
    optimizer_model: str = "claude-sonnet-4-6"
    max_samples: int = 50


# ---- Agent routes ----

agents_router = APIRouter(prefix="/v1/agents", tags=["agents"])


def _execute_agent_admin_tool(request: Request, tool: Any, params: Dict[str, Any]):
    """Execute an agent lifecycle operation through server security gates."""
    from nira.security.runtime import execute_secured_tool

    state = request.app.state
    return execute_secured_tool(
        tool,
        params,
        bus=getattr(state, "bus", None),
        capability_policy=getattr(state, "capability_policy", None),
        rate_limiter=getattr(state, "rate_limiter", None),
        agent_id="server:api",
    )


def _raise_agent_tool_failure(result: Any, *, not_found: bool = False) -> None:
    if result.success:
        return
    if "Capability '" in result.content and " denied " in result.content:
        raise HTTPException(status_code=403, detail=result.content)
    if result.content.startswith("Rate limit exceeded"):
        raise HTTPException(status_code=429, detail=result.content)
    raise HTTPException(status_code=404 if not_found else 400, detail=result.content)


@agents_router.get("")
async def list_agents(request: Request):
    """List available agent types and running agents."""
    try:
        from nira.tools.agent_tools import AgentListTool

        # Registry names and live agent metadata are administrative state,
        # just like spawn/send/kill.  Authorize before reading either source
        # so default-deny and rate-limit policies cannot be bypassed by GET.
        result = _execute_agent_admin_tool(request, AgentListTool(), {})
        _raise_agent_tool_failure(result)
    except ImportError:
        raise HTTPException(status_code=501, detail="Agent tools not available")

    registered = []
    try:
        import nira.agents  # noqa: F401 — side-effect registration
        from nira.core.registry import AgentRegistry

        for key in sorted(AgentRegistry.keys()):
            cls = AgentRegistry.get(key)
            registered.append(
                {
                    "key": key,
                    "class": cls.__name__,
                    "accepts_tools": getattr(cls, "accepts_tools", False),
                }
            )
    except Exception as exc:
        logger.warning("Failed to list registered agents: %s", exc)

    running = []
    try:
        from nira.tools.agent_tools import _SPAWNED_AGENTS

        running = [{"id": k, **v} for k, v in _SPAWNED_AGENTS.items()]
    except ImportError:
        pass

    return {"registered": registered, "running": running}


@agents_router.post("")
async def create_agent(req: AgentCreateRequest, request: Request):
    """Spawn a new agent."""
    try:
        from nira.tools.agent_tools import AgentSpawnTool

        tool = AgentSpawnTool()
        params = {"agent_type": req.agent_type}
        if req.tools:
            params["tools"] = ",".join(req.tools)
        if req.agent_id:
            params["agent_id"] = req.agent_id
        result = _execute_agent_admin_tool(request, tool, params)
        _raise_agent_tool_failure(result)
        return {
            "status": "created",
            "content": result.content,
            "metadata": result.metadata,
        }
    except ImportError:
        raise HTTPException(status_code=501, detail="Agent tools not available")


@agents_router.delete("/{agent_id}")
async def kill_agent(agent_id: str, request: Request):
    """Kill a running agent."""
    try:
        from nira.tools.agent_tools import AgentKillTool

        tool = AgentKillTool()
        result = _execute_agent_admin_tool(request, tool, {"agent_id": agent_id})
        _raise_agent_tool_failure(result, not_found=True)
        return {"status": "stopped", "agent_id": agent_id}
    except ImportError:
        raise HTTPException(status_code=501, detail="Agent tools not available")


@agents_router.post("/{agent_id}/message")
async def message_agent(agent_id: str, req: AgentMessageRequest, request: Request):
    """Send a message to a running agent."""
    try:
        from nira.tools.agent_tools import AgentSendTool

        tool = AgentSendTool()
        result = _execute_agent_admin_tool(
            request,
            tool,
            {"agent_id": agent_id, "message": req.message},
        )
        _raise_agent_tool_failure(result, not_found=True)
        return {"status": "sent", "content": result.content}
    except ImportError:
        raise HTTPException(status_code=501, detail="Agent tools not available")


# ---- Generation routes ----
#
# Images, audio and video. Every one of these takes longer than an HTTP
# request should, so they return a job id and the client polls. See
# nira.generate.jobs for why that is the only honest shape here.

generate_router = APIRouter(prefix="/v1/generate", tags=["generate"])


class GenerateRequest(BaseModel):
    prompt: str
    #: Backend-specific: model, steps, size, seed, frames, fps, mode, voice…
    options: Optional[Dict[str, Any]] = None


def _generation_queue():
    from nira.generate import get_queue

    return get_queue()


@generate_router.get("/capabilities")
def generation_capabilities():
    """What this install can generate, and what each option costs.

    The UI reads this rather than hard-coding a menu, so an install without
    the `generate` extra shows what is missing instead of buttons that fail.
    """
    from nira.generate import audio, image, video

    def describe(module, kinds) -> Dict[str, Any]:
        if not module.available():
            return {"available": False, "reason": module.why()}
        return {"available": True, **kinds}

    return {
        "image": describe(
            image,
            {
                "models": [
                    {"id": key, **{k: v for k, v in spec.items() if k != "repo"}}
                    for key, spec in image.MODELS.items()
                ],
                "default": image.DEFAULT_MODEL,
            },
        ),
        "audio": describe(
            audio,
            {
                "modes": list(audio.MODES),
                "music_models": list(audio.MUSIC_MODELS),
                "max_seconds": audio.MAX_MUSIC_SECONDS,
            },
        ),
        "video": describe(
            video,
            {
                "models": [
                    {"id": key, **{k: v for k, v in spec.items() if k != "repo"}}
                    for key, spec in video.MODELS.items()
                ],
                "default": video.DEFAULT_MODEL,
                "max_frames": video.MAX_FRAMES,
            },
        ),
        "queued": len(
            [j for j in _generation_queue().list() if j.status.value == "queued"]
        ),
    }


@generate_router.post("/{kind}")
def start_generation(kind: str, req: GenerateRequest):
    """Queue a generation job and return it immediately."""
    from nira.generate import JobKind

    try:
        job_kind = JobKind(kind)
    except ValueError:
        raise HTTPException(
            status_code=404,
            detail=f"Cannot generate {kind!r}. Try: image, audio, video.",
        ) from None

    prompt = (req.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="A prompt is required.")

    try:
        job = _generation_queue().submit(job_kind, prompt, **(req.options or {}))
    except ValueError as exc:
        # The backend is not installed. The message names the extra to add.
        raise HTTPException(status_code=501, detail=str(exc)) from exc

    body = job.to_public()
    body["queue_position"] = _generation_queue().position(job.id)
    return body


@generate_router.get("/jobs")
def list_generation_jobs(limit: int = 30):
    return {"jobs": [j.to_public() for j in _generation_queue().list(limit=limit)]}


@generate_router.get("/jobs/{job_id}")
def generation_job(job_id: str):
    job = _generation_queue().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such job.")
    body = job.to_public()
    body["queue_position"] = _generation_queue().position(job_id)
    return body


@generate_router.delete("/jobs/{job_id}")
def cancel_generation(job_id: str):
    """Stop a job. Backends check between steps, so this is not instant."""
    if not _generation_queue().cancel(job_id):
        raise HTTPException(
            status_code=409, detail="That job has already finished."
        )
    return {"status": "cancelling"}


@generate_router.get("/jobs/{job_id}/result")
def generation_result(job_id: str):
    """The finished file."""
    from fastapi.responses import FileResponse

    # Imported as a module rather than pulling the name in: a bound name is a
    # separate reference that a test (or anything else) patching the module
    # attribute cannot reach, and this function's whole job is deciding which
    # directory is allowed.
    from nira.generate import jobs as generate_jobs

    output_dir = generate_jobs.output_dir
    job = _generation_queue().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such job.")
    if job.status.value != "done" or not job.result:
        raise HTTPException(
            status_code=409,
            detail=f"That job is {job.status.value}, not finished.",
        )

    # Resolve under the output directory and verify containment: the id comes
    # from the URL, and a job whose result was somehow set to "../.." must not
    # become a file-read primitive.
    path = (output_dir() / job.result).resolve()
    if not path.is_file() or output_dir().resolve() not in path.parents:
        raise HTTPException(status_code=404, detail="That file is no longer here.")

    media = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".mp4": "video/mp4",
        ".gif": "image/gif",
        ".wav": "audio/wav",
    }.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media, filename=path.name)


# ---- Chat attachment routes ----
#
# Files a user attaches to a chat message. Bytes stay here; the browser holds
# an id. See nira.server.attachments for why.

attachments_router = APIRouter(prefix="/v1/chat/attachments", tags=["attachments"])


def _attachment_store(request: Request):
    """The per-process attachment store, created on first use."""
    from nira.server.attachments import AttachmentStore

    store = getattr(request.app.state, "attachment_store", None)
    if store is None:
        store = AttachmentStore()
        request.app.state.attachment_store = store
    return store


@attachments_router.post("")
async def upload_attachment(request: Request, file: UploadFile = File(...)):
    """Accept one file, extract it now, and return an id to reference it by.

    Reads with a hard ceiling rather than `await file.read()`.
    Every other upload path in this server reads the whole body into memory
    unbounded, which on a host that also binds to a tailnet is a
    memory-exhaustion primitive — and one that 152 GB of RAM makes feel
    survivable right up until it is not.
    """
    from nira.documents import ExtractionError
    from nira.server.attachments import (
        MAX_FILE_BYTES,
        AttachmentTooLarge,
    )

    filename = (file.filename or "").strip() or "attachment"

    # Read in chunks and stop the moment the limit is passed, so an oversized
    # upload costs one chunk over the limit rather than the whole file.
    chunks: List[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_FILE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"{filename} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB."
                ),
            )
        chunks.append(chunk)

    data = b"".join(chunks)
    store = _attachment_store(request)
    try:
        attachment = store.add(filename, data, mime=file.content_type or "")
    except AttachmentTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except ExtractionError as exc:
        # The message names the format and, where there is one, the fix.
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - unexpected parser failure
        logger.exception("attachment extraction failed")
        raise HTTPException(
            status_code=500, detail=f"Could not read {filename}: {exc}"
        ) from exc

    return attachment.to_public()


@attachments_router.get("/{attachment_id}/content")
def attachment_content(attachment_id: str, request: Request):
    """The image bytes, for the thumbnail the composer shows.

    Documents have no bytes to return — they were reduced to text at upload
    and the original was not kept.
    """
    from fastapi.responses import Response

    attachment = _attachment_store(request).get(attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail="That attachment has expired.")
    if not attachment.thumbnail:
        raise HTTPException(
            status_code=404, detail="This attachment has no preview image."
        )
    return Response(content=attachment.thumbnail, media_type=attachment.mime)


@attachments_router.delete("/{attachment_id}")
def discard_attachment(attachment_id: str, request: Request):
    """Drop an attachment the user removed before sending."""
    removed = _attachment_store(request).discard(attachment_id)
    return {"status": "deleted" if removed else "not_found"}


# ---- Memory routes ----

memory_router = APIRouter(prefix="/v1/memory", tags=["memory"])


def _get_memory_backend(request: Request):
    """Return the app-level memory backend, falling back to a fresh SQLiteMemory.

    Raises ``HTTPException(503)`` with an actionable message when the backend
    cannot be built because the mandatory ``nira_rust`` extension is not
    installed in the serving venv. This is deliberately distinct from a benign
    "memory not configured" case (which returns ``None``): a missing native
    extension must fail loudly, never silently degrade (#502).
    """
    backend = getattr(request.app.state, "memory_backend", None)
    if backend is None:
        from nira.tools.storage._stubs import MemoryBackendUnavailable

        try:
            from nira.tools.storage.sqlite import SQLiteMemory

            backend = SQLiteMemory()
        except MemoryBackendUnavailable as exc:
            # The native extension is missing — surface a loud, actionable error
            # rather than a misleading "no backend" / silent no-op.
            logger.error("%s", exc)
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception:
            # Memory is genuinely unconfigured for a benign reason — preserve
            # the existing graceful "no backend" behaviour.
            return None
    return backend


@memory_router.post("/store")
def memory_store(req: MemoryStoreRequest, request: Request):
    """Store content in memory."""
    backend = _get_memory_backend(request)
    if backend is None:
        # Memory is intentionally disabled; report it honestly instead of a
        # 200 that silently discards the write (#502).
        raise HTTPException(status_code=503, detail="Memory is not configured")
    try:
        backend.store(req.content, metadata=req.metadata or {})
        return {"status": "stored"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@memory_router.post("/search")
def memory_search(req: MemorySearchRequest, request: Request):
    """Search memory for relevant content."""
    backend = _get_memory_backend(request)
    if backend is None:
        return {"results": []}
    try:
        results = backend.retrieve(req.query, top_k=req.top_k)
        items = [
            {
                "content": r.content,
                "score": getattr(r, "score", 0.0),
                "metadata": getattr(r, "metadata", {}),
            }
            for r in results
        ]
        return {"results": items}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# Each retrieval backend and the third-party import it cannot start without.
# The UI offered all of these in a dropdown regardless; picking one whose
# dependency is absent left memory dead with nothing on screen to say why.
_BACKEND_REQUIREMENTS: Dict[str, tuple[str, ...]] = {
    "sqlite": (),
    "bm25": (),
    "hybrid": (),
    "faiss": ("faiss",),
    "colbert": ("torch", "colbert"),
}


def _available_backends() -> List[Dict[str, Any]]:
    """Report which memory backends this install can actually start.

    Probes with ``find_spec`` rather than importing: importing faiss or torch
    to answer a settings query would cost hundreds of milliseconds and a lot
    of memory on a request that just paints a dropdown.
    """
    from importlib.util import find_spec

    out: List[Dict[str, Any]] = []
    for name, requirements in _BACKEND_REQUIREMENTS.items():
        missing: List[str] = []
        for module in requirements:
            try:
                if find_spec(module) is None:
                    missing.append(module)
            except (ImportError, ValueError):
                missing.append(module)
        out.append(
            {
                "id": name,
                "available": not missing,
                "missing": missing,
            }
        )
    return out


def _memory_settings(request: Request) -> Any:
    """Return the live memory/storage config, loading one if the app has none."""
    config = getattr(request.app.state, "config", None)
    if config is None:
        from nira.core.config import load_config

        config = load_config()
    return config


@memory_router.get("/stats")
def memory_stats(request: Request):
    """Get memory backend statistics.

    Reports ``enabled`` — whether the server is actually recording memories —
    alongside the counts. Without it the UI had no way to know, and its toggle
    defaulted to showing memory ON while the server had it off: a switch that
    described a state nobody was in.
    """
    config = _memory_settings(request)
    enabled = bool(getattr(config.memory, "enabled", False))
    context_from_memory = bool(getattr(config.agent, "context_from_memory", False))

    # Two different stores answer to the word "memory", and the UI only ever
    # showed one of them. `entries` counts documents in the retrieval backend
    # (what /memory/index and /memory/store write). `facts` counts what the
    # background memory service has learned from conversations on its own —
    # which is the thing a user means by "does it remember me". Showing only
    # the first left the panel reading 0 entries on a server that was in fact
    # remembering.
    service = getattr(request.app.state, "memory_service", None)
    facts: Optional[int] = None
    service_running: Optional[bool] = None
    if service is not None:
        # Read the two independently. Sharing one try meant a failure in
        # either blanked both, which is how `is_running` being a property
        # rather than a method (calling a bool raises TypeError) showed up as
        # "there is no memory service" on a server that had one running.
        try:
            facts = service.fact_count()
        except Exception:
            # A stats call must not 500 because the fact store is briefly
            # locked by the extractor thread mid-write.
            logger.debug("memory fact_count failed", exc_info=True)
        try:
            running = service.is_running
            service_running = bool(running() if callable(running) else running)
        except Exception:
            logger.debug("memory is_running failed", exc_info=True)

    backend = _get_memory_backend(request)
    if backend is None:
        return {
            "entries": 0,
            "backend": "none",
            "status": "not_configured",
            "enabled": enabled,
            "context_from_memory": context_from_memory,
            "facts": facts,
            "service_running": service_running,
        }
    try:
        return {
            "entries": backend.count(),
            "backend": getattr(backend, "backend_id", "unknown"),
            "enabled": enabled,
            "context_from_memory": context_from_memory,
            "facts": facts,
            "service_running": service_running,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@memory_router.get("/config")
async def memory_config(request: Request):
    """Return current memory configuration.

    Reports memory as *unavailable* (rather than falsely claiming
    ``backend_type: sqlite``) when the native ``nira_rust`` extension is
    missing, so the UI can show the real cause instead of a healthy-looking
    config that backs a silent no-op (#502).
    """
    try:
        config = getattr(request.app.state, "config", None)
        if config is None:
            from nira.core.config import load_config

            config = load_config()
        backend = getattr(request.app.state, "memory_backend", None)
        available = True
        detail: Optional[str] = None
        if backend is None:
            from nira.tools.storage._stubs import MemoryBackendUnavailable

            try:
                from nira.tools.storage.sqlite import SQLiteMemory

                backend = SQLiteMemory()
            except MemoryBackendUnavailable as exc:
                available = False
                detail = str(exc)
            except Exception:
                # Benign: cannot construct a probe backend here, but the
                # configured default is still what would be used.
                pass
        return {
            "backend_type": (
                backend.backend_id
                if backend is not None
                else config.memory.default_backend
            ),
            "available": available,
            "detail": detail,
            "context_top_k": config.memory.context_top_k,
            "context_min_score": config.memory.context_min_score,
            "context_max_tokens": config.memory.context_max_tokens,
            "context_from_memory": config.agent.context_from_memory,
            "enabled": bool(getattr(config.memory, "enabled", False)),
            "default_backend": config.memory.default_backend,
            "backends": _available_backends(),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@memory_router.put("/config")
async def memory_config_update(req: MemoryConfigRequest, request: Request):
    """Persist memory settings to ``config.toml`` and apply them live.

    The Settings panel used to keep all of this in ``localStorage``, where the
    server never saw it: the controls moved, nothing changed, and clearing site
    data erased the "settings". Writing the config file is what makes a choice
    outlive the tab, the app restart and the machine reboot.
    """
    from nira.core.config_writer import update_config_section

    config = _memory_settings(request)

    # [memory] in the file maps onto tools.storage in the dataclass; the two
    # boolean-ish keys below live in different tables, so split them out.
    memory_keys = {
        "enabled": req.enabled,
        "context_top_k": req.context_top_k,
        "context_min_score": req.context_min_score,
        "context_max_tokens": req.context_max_tokens,
        "default_backend": req.default_backend,
    }
    memory_values = {k: v for k, v in memory_keys.items() if v is not None}

    if req.context_top_k is not None and req.context_top_k < 0:
        raise HTTPException(status_code=422, detail="context_top_k must be >= 0")
    if req.context_max_tokens is not None and req.context_max_tokens < 0:
        raise HTTPException(status_code=422, detail="context_max_tokens must be >= 0")
    if req.context_min_score is not None and not (0.0 <= req.context_min_score <= 1.0):
        raise HTTPException(
            status_code=422, detail="context_min_score must be between 0 and 1"
        )
    if req.default_backend is not None:
        known = {b["id"]: b for b in _available_backends()}
        chosen = known.get(req.default_backend)
        if chosen is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Unknown memory backend '{req.default_backend}'. "
                    f"Available: {', '.join(sorted(known))}"
                ),
            )
        if not chosen["available"]:
            # Better a refusal the user can read than a config that saves
            # cleanly and leaves memory dead on the next start.
            raise HTTPException(
                status_code=422,
                detail=(
                    f"The '{req.default_backend}' backend needs "
                    f"{', '.join(chosen['missing'])}, which is not installed."
                ),
            )

    try:
        if memory_values:
            update_config_section("memory", memory_values)
        if req.context_from_memory is not None:
            update_config_section(
                "agent", {"context_from_memory": req.context_from_memory}
            )
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Could not write config: {exc}"
        ) from exc

    # Apply to the running server too, so the change takes effect without a
    # restart. Persisting and applying are separate steps precisely because a
    # setting that only lives in memory is the bug this endpoint exists to fix.
    for key, value in memory_values.items():
        setattr(config.memory, key, value)
    if req.context_from_memory is not None:
        config.agent.context_from_memory = req.context_from_memory

    return {
        "status": "saved",
        "enabled": bool(getattr(config.memory, "enabled", False)),
        "context_from_memory": bool(config.agent.context_from_memory),
        "context_top_k": config.memory.context_top_k,
        "context_min_score": config.memory.context_min_score,
        "context_max_tokens": config.memory.context_max_tokens,
        "default_backend": config.memory.default_backend,
    }


@memory_router.post("/index")
def memory_index(req: MemoryIndexRequest, request: Request):
    """Index files from a path into memory."""
    try:
        import os
        from pathlib import Path

        from nira.security.file_policy import is_sensitive_file
        from nira.tools.storage.ingest import ingest_path

        target = Path(req.path).expanduser().resolve()
        if not target.exists():
            raise HTTPException(status_code=404, detail=f"Path not found: {req.path}")

        # Sandbox: when workspace roots are configured via NIRA_WORKSPACE
        # (os.pathsep-separated), only allow indexing inside them. This endpoint
        # must not become an arbitrary-filesystem read primitive over the API.
        workspace = os.environ.get("NIRA_WORKSPACE", "").strip()
        if workspace:
            roots = [
                Path(d).expanduser().resolve()
                for d in workspace.split(os.pathsep)
                if d.strip()
            ]
            if not any(target == root or root in target.parents for root in roots):
                raise HTTPException(
                    status_code=403,
                    detail="Path is outside the allowed workspace directories.",
                )
        # Never ingest sensitive files (.env, private keys, credentials, ...).
        if target.is_file() and is_sensitive_file(target):
            raise HTTPException(
                status_code=403, detail="Refusing to index a sensitive file."
            )

        backend = _get_memory_backend(request)
        if backend is None:
            raise HTTPException(status_code=503, detail="Memory is not configured")

        chunks = ingest_path(target)
        stored = 0
        for chunk in chunks:
            metadata = {"source": getattr(chunk, "source", str(target))}
            if hasattr(chunk, "metadata") and chunk.metadata:
                metadata.update(chunk.metadata)
            backend.store(chunk.content, metadata=metadata)
            stored += 1

        result = {"status": "indexed", "chunks_indexed": stored}
        if stored == 0:
            # "indexed" must never silently mean "stored nothing". Surface why
            # so a folder of short notes doesn't look like a successful no-op
            # (#502 follow-up).
            result["note"] = (
                "no content was indexed — the path contained no readable "
                "documents with indexable text"
            )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---- Traces routes ----

traces_router = APIRouter(prefix="/v1/traces", tags=["traces"])


def _serialise_trace(trace) -> dict:
    """Convert a Trace dataclass to a frontend-friendly dict."""
    import datetime
    from dataclasses import asdict

    d = asdict(trace)
    d["id"] = d.pop("trace_id", "")
    started = d.pop("started_at", 0.0)
    d["created_at"] = (
        datetime.datetime.fromtimestamp(started, tz=datetime.timezone.utc).isoformat()
        if started
        else None
    )
    dur = d.pop("total_latency_seconds", 0.0)
    d["duration_ms"] = round(dur * 1000)
    for step in d.get("steps", []):
        st = step.get("step_type")
        if hasattr(st, "value"):
            step["step_type"] = st.value
    return d


@traces_router.get("")
async def list_traces(request: Request, limit: int = 20):
    """List recent traces."""
    try:
        store = getattr(request.app.state, "trace_store", None)
        if store is None:
            return {"traces": []}
        traces = store.list_traces(limit=limit)
        items = [_serialise_trace(t) for t in traces]
        return {"traces": items}
    except Exception as exc:
        return {"traces": [], "error": str(exc)}


@traces_router.get("/{trace_id}")
async def get_trace(trace_id: str, request: Request):
    """Get a specific trace by ID."""
    try:
        store = getattr(request.app.state, "trace_store", None)
        if store is None:
            raise HTTPException(status_code=404, detail="Trace not found")
        trace = store.get(trace_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="Trace not found")
        return _serialise_trace(trace)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---- Telemetry routes ----

telemetry_router = APIRouter(prefix="/v1/telemetry", tags=["telemetry"])


def _telemetry_db_path(request: Request) -> Path:
    """Resolve telemetry storage from the active app configuration.

    ``DEFAULT_CONFIG_DIR`` is fixed when :mod:`nira.core.config` is
    imported, so it cannot honor a later ``NIRA_HOME`` override.  The
    running app's config is authoritative; lightweight apps that include these
    routes directly fall back to the env-aware path resolver.
    """
    config = getattr(request.app.state, "config", None)
    telemetry = getattr(config, "telemetry", None)
    configured_path = getattr(telemetry, "db_path", None)
    if configured_path:
        return Path(configured_path).expanduser()

    from nira.core.paths import get_config_dir

    return get_config_dir() / "telemetry.db"


@telemetry_router.get("/stats")
async def telemetry_stats(request: Request):
    """Get aggregated telemetry statistics."""
    try:
        from dataclasses import asdict

        from nira.telemetry.aggregator import TelemetryAggregator

        db_path = _telemetry_db_path(request)
        if not db_path.exists():
            return {"total_requests": 0, "total_tokens": 0}

        session_start = getattr(request.app.state, "session_start", None)
        agg = TelemetryAggregator(db_path)
        try:
            stats = agg.summary(since=session_start)
            d = asdict(stats)
            d.pop("per_model", None)
            d.pop("per_engine", None)
            d["total_requests"] = d.pop("total_calls", 0)
            return d
        finally:
            agg.close()
    except Exception as exc:
        return {"error": str(exc)}


@telemetry_router.get("/energy")
async def telemetry_energy(request: Request):
    """Get energy monitoring data."""
    try:
        from nira.telemetry.aggregator import TelemetryAggregator

        db_path = _telemetry_db_path(request)
        if not db_path.exists():
            return {
                "total_energy_j": 0,
                "energy_per_token_j": 0,
                "avg_power_w": 0,
                "cpu_temp_c": None,
                "gpu_temp_c": None,
            }

        session_start = getattr(request.app.state, "session_start", None)
        agg = TelemetryAggregator(db_path)
        try:
            stats = agg.summary(since=session_start)
            total_energy = stats.total_energy_joules
            total_tokens = stats.total_tokens
            total_latency = stats.total_latency
            return {
                "total_energy_j": total_energy,
                "energy_per_token_j": (
                    total_energy / total_tokens if total_tokens > 0 else 0
                ),
                "avg_power_w": (
                    total_energy / total_latency if total_latency > 0 else 0
                ),
                "cpu_temp_c": None,
                "gpu_temp_c": None,
            }
        finally:
            agg.close()
    except Exception as exc:
        return {"error": str(exc)}


# ---- Network routes ----
#
# Which address this machine hands its own devices. Everyone's network is
# different — a tailnet, a router with a reserved lease, neither — so the
# choice belongs to the person who owns it rather than to a detector.

network_router = APIRouter(prefix="/v1/network", tags=["network"])


class NetworkConfigRequest(BaseModel):
    """The network settings the UI may change; omitted fields are untouched."""

    mode: Optional[str] = None
    advertise_host: Optional[str] = None
    advertise_port: Optional[int] = None
    advertise_scheme: Optional[str] = None
    bind_host: Optional[str] = None


def _network_state(config: Any, port: int) -> Dict[str, Any]:
    from nira.server.advertise import candidates, resolve_advertise_url

    options = [
        {
            "kind": c.kind,
            "host": c.host,
            "url": c.url(port),
            "reachable_off_machine": c.reachable_off_machine,
            "secure_context": c.secure_context,
            "stable": c.stable,
            "note": c.note,
        }
        for c in candidates()
    ]

    current: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    try:
        url, chosen = resolve_advertise_url(config, port)
        current = {
            "url": url,
            "kind": chosen.kind,
            "reachable_off_machine": chosen.reachable_off_machine,
            "secure_context": chosen.secure_context,
            "stable": chosen.stable,
            "note": chosen.note,
        }
    except ValueError as exc:
        # A mode that cannot be satisfied is the user's own setting failing,
        # not a server fault — report it as state so the panel can say which
        # setting to change, rather than as a 500.
        error = str(exc)

    return {
        "mode": config.network.mode,
        "advertise_host": config.network.advertise_host,
        "advertise_port": config.network.advertise_port,
        "advertise_scheme": config.network.advertise_scheme,
        "bind_host": config.network.bind_host,
        "port": port,
        "candidates": options,
        "current": current,
        "error": error,
    }


@network_router.get("/config")
def network_config(request: Request):
    """Report the addresses this machine could advertise, and the one in use."""
    config = _memory_settings(request)
    port = int(getattr(config.server, "port", 8000))
    try:
        return _network_state(config, port)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@network_router.put("/config")
def network_config_update(req: NetworkConfigRequest, request: Request):
    """Persist network settings to config.toml and apply them live."""
    from nira.core.config_writer import update_config_section
    from nira.server.advertise import MODES

    config = _memory_settings(request)

    if req.mode is not None and req.mode not in MODES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown mode {req.mode!r}. Use one of: {', '.join(MODES)}",
        )
    if req.advertise_scheme not in (None, "", "http", "https"):
        raise HTTPException(
            status_code=422, detail="advertise_scheme must be 'http' or 'https'"
        )
    if req.advertise_port is not None and not (0 <= req.advertise_port <= 65535):
        raise HTTPException(
            status_code=422, detail="advertise_port must be between 0 and 65535"
        )

    # Naming a host while leaving the mode alone would save the setting and
    # then ignore it — auto never reads advertise_host. Choosing a host is
    # choosing manual unless the caller says otherwise.
    mode = req.mode
    if mode is None and req.advertise_host:
        mode = "manual"

    effective_host = (
        req.advertise_host
        if req.advertise_host is not None
        else config.network.advertise_host
    )
    if mode == "manual" and not effective_host:
        raise HTTPException(
            status_code=422, detail="mode 'manual' needs advertise_host"
        )

    values = {
        "mode": mode,
        "advertise_host": req.advertise_host,
        "advertise_port": req.advertise_port,
        "advertise_scheme": req.advertise_scheme,
        "bind_host": req.bind_host,
    }
    values = {k: v for k, v in values.items() if v is not None}
    if not values:
        raise HTTPException(status_code=422, detail="Nothing to change")

    try:
        update_config_section("network", values)
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Could not write config: {exc}"
        ) from exc

    for key, value in values.items():
        setattr(config.network, key, value)

    port = int(getattr(config.server, "port", 8000))
    state = _network_state(config, port)
    state["status"] = "saved"
    return state


# ---- Skills routes ----

skills_router = APIRouter(prefix="/v1/skills", tags=["skills"])


@skills_router.get("")
async def list_skills(request: Request):
    """List installed skills."""
    try:
        from nira.core.registry import SkillRegistry

        skills = []
        for key in sorted(SkillRegistry.keys()):
            skills.append({"name": key})
        return {"skills": skills}
    except Exception as exc:
        logger.warning("Failed to list skills: %s", exc)
        return {"skills": []}


@skills_router.post("")
async def install_skill(request: Request):
    """Install a skill (placeholder)."""
    return {
        "status": "not_implemented",
        "message": "Use TOML files in ~/.nira/skills/",
    }


@skills_router.delete("/{skill_name}")
async def remove_skill(skill_name: str, request: Request):
    """Remove a skill (placeholder)."""
    return {
        "status": "not_implemented",
        "message": "Skill removal not yet supported via API",
    }


# ---- Sessions routes ----

sessions_router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


# These imported ``nira.sessions.store``, which does not exist — SessionStore
# lives in ``nira.sessions.session`` — and then called ``recent()`` and
# ``get()``, which it does not have. A blanket ``except Exception`` turned all
# of that into ``{"sessions": [], "error": ...}``, so the endpoint reported no
# sessions rather than reporting that it was broken, and did so for as long as
# nobody read the error field.


def _session_store(request: Request):  # noqa: ANN202
    store = getattr(request.app.state, "session_store", None)
    if store is None:
        from nira.sessions.session import SessionStore

        store = SessionStore()
        request.app.state.session_store = store
    return store


@sessions_router.get("")
async def list_sessions(request: Request, limit: int = 20):
    """List recent sessions, newest first."""
    store = _session_store(request)
    sessions = store.list_sessions(limit=max(1, min(200, limit)))
    return {
        "sessions": [_session_dict(session) for session in sessions],
        "count": len(sessions),
    }


@sessions_router.get("/{session_id}")
async def get_session(session_id: str, request: Request):
    """One session, with its messages."""
    store = _session_store(request)
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return _session_dict(session, messages=True)


def _session_dict(session: Any, *, messages: bool = False) -> dict:
    """Serialise a Session without requiring it to know about HTTP."""
    identity = getattr(session, "identity", None)
    body = {
        "session_id": session.session_id,
        "user_id": getattr(identity, "user_id", "") if identity else "",
        "display_name": getattr(identity, "display_name", "") if identity else "",
        "created_at": session.created_at,
        "last_activity": session.last_activity,
        "metadata": session.metadata,
        "message_count": len(session.messages),
    }
    if messages:
        body["messages"] = [
            {
                "role": message.role,
                "content": message.content,
                "channel": message.channel,
                "timestamp": message.timestamp,
            }
            for message in session.messages
        ]
    return body


# ---- Budget routes ----

budget_router = APIRouter(prefix="/v1/budget", tags=["budget"])

_budget_limits: Dict[str, Any] = {
    "max_tokens_per_day": None,
    "max_requests_per_hour": None,
}
_budget_usage: Dict[str, int] = {
    "tokens_today": 0,
    "requests_this_hour": 0,
}


@budget_router.get("")
async def get_budget(request: Request):
    """Get current budget usage and limits."""
    return {"limits": _budget_limits, "usage": _budget_usage}


@budget_router.put("/limits")
async def set_budget_limits(req: BudgetLimitsRequest, request: Request):
    """Update budget limits."""
    if req.max_tokens_per_day is not None:
        _budget_limits["max_tokens_per_day"] = req.max_tokens_per_day
    if req.max_requests_per_hour is not None:
        _budget_limits["max_requests_per_hour"] = req.max_requests_per_hour
    return {"status": "updated", "limits": _budget_limits}


# ---- Prometheus metrics ----

metrics_router = APIRouter(tags=["metrics"])


@metrics_router.get("/metrics")
async def prometheus_metrics(request: Request):
    """Prometheus-compatible metrics endpoint."""
    try:
        from nira.telemetry.aggregator import TelemetryAggregator

        db_path = _telemetry_db_path(request)
        if not db_path.exists():
            from starlette.responses import PlainTextResponse

            return PlainTextResponse("# no telemetry data\n", media_type="text/plain")

        agg = TelemetryAggregator(db_path)
        try:
            stats = agg.summary()
        finally:
            agg.close()

        avg_latency_ms = (
            (stats.total_latency / stats.total_calls) * 1000
            if stats.total_calls
            else 0.0
        )

        lines = [
            "# HELP nira_requests_total Total requests processed",
            "# TYPE nira_requests_total counter",
            f"nira_requests_total {stats.total_calls}",
            "# HELP nira_tokens_total Total tokens generated",
            "# TYPE nira_tokens_total counter",
            f"nira_tokens_total {stats.total_tokens}",
            "# HELP nira_latency_avg_ms Average latency in milliseconds",
            "# TYPE nira_latency_avg_ms gauge",
            f"nira_latency_avg_ms {avg_latency_ms}",
        ]
        from starlette.responses import PlainTextResponse

        return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain")
    except Exception as exc:
        logger.warning("Failed to collect Prometheus metrics: %s", exc)
        from starlette.responses import PlainTextResponse

        return PlainTextResponse("# No metrics available\n", media_type="text/plain")


# ---- WebSocket streaming routes ----

websocket_router = APIRouter(tags=["websocket"])
_SYNC_STREAM_END = object()


async def _next_sync_stream(iterator: Any) -> Any:
    """Fetch one sync-stream item without blocking or racing cancellation."""
    next_task = asyncio.create_task(asyncio.to_thread(next, iterator, _SYNC_STREAM_END))
    try:
        return await asyncio.shield(next_task)
    except asyncio.CancelledError:
        # ``to_thread`` cannot stop a running ``next()``. Wait for it before
        # allowing the iterator to be closed so cancellation cannot race a
        # generator that is still executing in the worker thread.
        try:
            await next_task
        except Exception:
            pass
        raise


async def _iterate_sync_stream(iterator: Any):
    """Adapt a blocking iterator to an async generator, closing it safely."""
    try:
        while True:
            item = await _next_sync_stream(iterator)
            if item is _SYNC_STREAM_END:
                return
            yield item
    finally:
        close = getattr(iterator, "close", None)
        if callable(close):
            try:
                await asyncio.to_thread(close)
            except Exception as exc:
                logger.warning("Failed to close synchronous engine stream: %s", exc)


def _record_ws_trace(
    trace_store,
    *,
    query: str,
    result: str,
    model: str,
    started_at: float,
    ended_at: float,
) -> None:
    """Record a trace for a completed WebSocket chat (best-effort)."""
    if trace_store is None or not result:
        return
    from nira.traces.collector import record_response_trace

    record_response_trace(
        trace_store,
        query=query,
        result=result,
        model=model,
        started_at=started_at,
        ended_at=ended_at,
    )


@websocket_router.websocket("/v1/chat/stream")
async def websocket_chat_stream(websocket: WebSocket):
    """Stream chat responses over a WebSocket connection.

    Accepts JSON messages of the form::

        {"message": "...", "model": "...", "agent": "..."}

    Sends back JSON chunks::

        {"type": "chunk", "content": "..."}   -- per-token streaming
        {"type": "done",  "content": "..."}   -- final assembled response
        {"type": "error", "detail": "..."}    -- on failure
    """
    from nira.server.auth_middleware import authenticate_websocket

    expected_key = getattr(websocket.app.state, "api_key", "")
    authorized, subprotocol = authenticate_websocket(
        websocket,
        expected_key,
        device_store=getattr(websocket.app.state, "device_store", None),
        required_scope_name="ask",
    )
    if not authorized:
        # Closing before accept rejects the HTTP upgrade request.
        await websocket.close(code=1008)
        return
    await websocket.accept(subprotocol=subprotocol)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                await websocket.send_json(
                    {"type": "error", "detail": "Invalid JSON"},
                )
                continue

            message = data.get("message")
            if not message:
                await websocket.send_json(
                    {"type": "error", "detail": "Missing 'message' field"},
                )
                continue

            model = data.get("model") or getattr(
                websocket.app.state,
                "model",
                "default",
            )
            engine = getattr(websocket.app.state, "engine", None)
            if engine is None:
                await websocket.send_json(
                    {"type": "error", "detail": "No engine configured"},
                )
                continue

            messages = [{"role": "user", "content": message}]

            # This WS path streams straight from the engine (no agent /
            # TraceCollector), so record the interaction directly once it
            # finishes — otherwise WebSocket chats never reach traces.db.
            import time as _time

            trace_store = getattr(websocket.app.state, "trace_store", None)
            _ws_started_at = _time.time()

            try:
                # Prefer streaming if the engine supports it
                stream_fn = getattr(engine, "stream", None)
                if stream_fn is not None and (
                    inspect.isasyncgenfunction(stream_fn) or callable(stream_fn)
                ):
                    full_content = ""
                    try:
                        gen = stream_fn(messages, model=model)
                        # Handle both async and sync generators
                        if inspect.isasyncgen(gen):
                            async for token in gen:
                                full_content += token
                                await websocket.send_json(
                                    {"type": "chunk", "content": token},
                                )
                        else:
                            # Each ``next()`` can perform a blocking upstream
                            # read, so offload iteration one item at a time.
                            async for token in _iterate_sync_stream(iter(gen)):
                                full_content += token
                                await websocket.send_json(
                                    {"type": "chunk", "content": token},
                                )
                    except TypeError:
                        # stream() didn't return an iterable; fall back to
                        # generate(). It makes a blocking upstream call, so run
                        # it in a worker thread to keep the event loop free.
                        result = await asyncio.to_thread(
                            engine.generate, messages, model=model
                        )
                        content = (
                            result.get("content", "")
                            if isinstance(
                                result,
                                dict,
                            )
                            else str(result)
                        )
                        full_content = content
                        await websocket.send_json(
                            {"type": "chunk", "content": content},
                        )
                    await websocket.send_json(
                        {"type": "done", "content": full_content},
                    )
                    _record_ws_trace(
                        trace_store,
                        query=message,
                        result=full_content,
                        model=model,
                        started_at=_ws_started_at,
                        ended_at=_time.time(),
                    )
                else:
                    # No stream method — single-shot generate. Blocking upstream
                    # call, so run in a worker thread to keep the event loop free.
                    result = await asyncio.to_thread(
                        engine.generate, messages, model=model
                    )
                    content = (
                        result.get("content", "")
                        if isinstance(
                            result,
                            dict,
                        )
                        else str(result)
                    )
                    await websocket.send_json(
                        {"type": "chunk", "content": content},
                    )
                    await websocket.send_json(
                        {"type": "done", "content": content},
                    )
                    _record_ws_trace(
                        trace_store,
                        query=message,
                        result=content,
                        model=model,
                        started_at=_ws_started_at,
                        ended_at=_time.time(),
                    )
            except WebSocketDisconnect:
                raise
            except Exception as exc:
                await websocket.send_json(
                    {"type": "error", "detail": str(exc)},
                )
    except WebSocketDisconnect:
        pass  # Client disconnected — nothing to clean up


# ---- Learning routes ----

learning_router = APIRouter(prefix="/v1/learning", tags=["learning"])


@learning_router.get("/stats")
async def learning_stats(request: Request):
    """Return learning system statistics across all sub-policies."""
    result: Dict[str, Any] = {}

    # Skill discovery
    try:
        from nira.learning.agents.skill_discovery import SkillDiscovery

        discovery = SkillDiscovery()
        result["skill_discovery"] = {
            "available": True,
            "discovered_count": len(discovery.discovered_skills),
        }
    except Exception as exc:
        logger.warning("Failed to load skill discovery stats: %s", exc)
        result["skill_discovery"] = {"available": False}

    return result


@learning_router.get("/policy")
async def learning_policy(request: Request):
    """Return current routing policy configuration."""
    result: Dict[str, Any] = {}

    # Load config and extract learning section
    try:
        from nira.core.config import load_config

        config = load_config()
        lc = config.learning
        result["enabled"] = lc.enabled
        result["update_interval"] = lc.update_interval
        result["auto_update"] = lc.auto_update
        result["routing"] = {
            "policy": lc.routing.policy,
            "min_samples": lc.routing.min_samples,
        }
        result["intelligence"] = {
            "policy": lc.intelligence.policy,
        }
        result["agent"] = {
            "policy": lc.agent.policy,
        }
        result["metrics"] = {
            "accuracy_weight": lc.metrics.accuracy_weight,
            "latency_weight": lc.metrics.latency_weight,
            "cost_weight": lc.metrics.cost_weight,
            "efficiency_weight": lc.metrics.efficiency_weight,
        }
    except Exception as exc:
        logger.warning("Failed to load learning config: %s", exc)
        result["enabled"] = False
        result["routing"] = {"policy": "heuristic", "min_samples": 5}
        result["intelligence"] = {"policy": "none"}
        result["agent"] = {"policy": "none"}
        result["metrics"] = {}

    return result


# ---- Speech routes ----

speech_router = APIRouter(prefix="/v1/speech", tags=["speech"])


@speech_router.post("/transcribe")
async def transcribe_speech(request: Request):
    """Transcribe uploaded audio to text."""
    backend = getattr(request.app.state, "speech_backend", None)
    if backend is None:
        raise HTTPException(status_code=501, detail="Speech backend not configured")

    form = await request.form()
    audio_file = form.get("file")
    if audio_file is None:
        raise HTTPException(status_code=400, detail="Missing 'file' field")

    audio_bytes = await audio_file.read()
    language = form.get("language")

    # Detect format from filename
    filename = getattr(audio_file, "filename", "audio.wav")
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "wav"

    try:
        result = await asyncio.to_thread(
            backend.transcribe,
            audio_bytes,
            format=ext,
            language=language or None,
        )
    except Exception as exc:
        logger.exception("Speech transcription failed")
        raise HTTPException(
            status_code=500,
            detail=f"Speech transcription failed: {exc}",
        ) from exc

    return {
        "text": result.text,
        "language": result.language,
        "confidence": result.confidence,
        "duration_seconds": result.duration_seconds,
    }


@speech_router.get("/health")
async def speech_health(request: Request):
    """Check if a speech backend is available."""
    backend = getattr(request.app.state, "speech_backend", None)
    if backend is None:
        return {"available": False, "reason": "No speech backend configured"}
    try:
        available = backend.health()
        reason = None
    except Exception as exc:
        logger.exception("Speech health check failed")
        available = False
        reason = str(exc)

    if not available and reason is None:
        last_error = getattr(backend, "last_error", None)
        if callable(last_error):
            reason = last_error()

    return {
        "available": available,
        "backend": backend.backend_id,
        **({"reason": reason} if reason else {}),
    }


# ---- Feedback routes ----

feedback_router = APIRouter(prefix="/v1/feedback", tags=["feedback"])


@feedback_router.post("")
async def submit_feedback(req: FeedbackScoreRequest, request: Request):
    """Submit feedback for a trace."""
    try:
        from nira.core.config import DEFAULT_CONFIG_DIR
        from nira.traces.store import TraceStore

        db_path = DEFAULT_CONFIG_DIR / "traces.db"
        if not db_path.exists():
            raise HTTPException(status_code=404, detail="No trace database")

        store = TraceStore(db_path)
        updated = store.update_feedback(req.trace_id, req.score)
        store.close()

        if not updated:
            raise HTTPException(
                status_code=404, detail=f"Trace '{req.trace_id}' not found"
            )
        return {"status": "recorded", "trace_id": req.trace_id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@feedback_router.get("/stats")
async def feedback_stats(request: Request):
    """Get feedback statistics."""
    return {"total": 0, "mean_score": 0.0}


# ---- Optimize routes ----

optimize_router = APIRouter(prefix="/v1/optimize", tags=["optimize"])


@optimize_router.get("/runs")
async def list_optimize_runs(request: Request):
    """List optimization runs."""
    try:
        from nira.core.config import DEFAULT_CONFIG_DIR
        from nira.learning.optimize.store import OptimizationStore

        db_path = DEFAULT_CONFIG_DIR / "optimize.db"
        if not db_path.exists():
            return {"runs": []}

        store = OptimizationStore(db_path)
        runs = store.list_runs()
        store.close()
        return {"runs": runs}
    except Exception as exc:
        logger.warning("Failed to list optimization runs: %s", exc)
        return {"runs": []}


@optimize_router.get("/runs/{run_id}")
async def get_optimize_run(run_id: str, request: Request):
    """Get optimization run details."""
    try:
        from nira.core.config import DEFAULT_CONFIG_DIR
        from nira.learning.optimize.store import OptimizationStore

        db_path = DEFAULT_CONFIG_DIR / "optimize.db"
        if not db_path.exists():
            return {"run_id": run_id, "status": "not_found"}

        store = OptimizationStore(db_path)
        run = store.get_run(run_id)
        store.close()

        if run is None:
            return {"run_id": run_id, "status": "not_found"}

        return {
            "run_id": run.run_id,
            "status": run.status,
            "benchmark": run.benchmark,
            "trials": len(run.trials),
            "best_trial_id": (run.best_trial.trial_id if run.best_trial else None),
        }
    except Exception as exc:
        logger.warning("Failed to get optimization run %s: %s", run_id, exc)
        return {"run_id": run_id, "status": "not_found"}


@optimize_router.post("/runs")
async def start_optimize_run(req: OptimizeRunRequest, request: Request):
    """Start a new optimization run."""
    return {"status": "started", "run_id": "placeholder"}


def include_all_routes(app) -> None:
    """Include all extended API routers in a FastAPI app."""
    from nira.server.approval_routes import (
        router as approval_router,  # noqa: PLC0415
    )

    app.include_router(approval_router)
    app.include_router(agents_router)
    app.include_router(attachments_router)
    app.include_router(generate_router)
    app.include_router(memory_router)
    app.include_router(network_router)
    app.include_router(traces_router)
    app.include_router(telemetry_router)
    app.include_router(skills_router)
    app.include_router(sessions_router)
    app.include_router(budget_router)
    app.include_router(metrics_router)
    app.include_router(websocket_router)
    app.include_router(learning_router)
    app.include_router(speech_router)
    app.include_router(feedback_router)
    app.include_router(optimize_router)

    # Agent Manager routes (if available)
    try:
        if hasattr(app.state, "agent_manager") and app.state.agent_manager:
            from nira.server.agent_manager_routes import (  # noqa: PLC0415
                create_agent_manager_router,
            )

            (
                agents_r,
                templates_r,
                global_r,
                tools_r,
                sendblue_r,
            ) = create_agent_manager_router(app.state.agent_manager)
            app.include_router(agents_r)
            app.include_router(templates_r)
            app.include_router(global_r)
            app.include_router(tools_r)
            app.include_router(sendblue_r)
    except ImportError:
        pass

    # WebSocket bridge for real-time agent events. Must subscribe on the
    # same EventBus instance channels/agents actually publish to
    # (app.state.bus, set in server/app.py) — the get_event_bus() global
    # singleton is a *different* bus that nothing in `nira serve` ever
    # publishes to, so events silently never reached this endpoint.
    try:
        from nira.core.events import get_event_bus
        from nira.server.ws_bridge import create_ws_router

        ws_router = create_ws_router(getattr(app.state, "bus", None) or get_event_bus())
        app.include_router(ws_router)
    except Exception:
        logger.debug("WebSocket bridge not available", exc_info=True)

    try:
        from nira.server.device_routes import devices_router

        app.include_router(devices_router)
    except Exception:
        logger.debug("Device routes not available", exc_info=True)


__all__ = [
    "include_all_routes",
    "agents_router",
    "attachments_router",
    "generate_router",
    "memory_router",
    "network_router",
    "traces_router",
    "telemetry_router",
    "skills_router",
    "sessions_router",
    "budget_router",
    "metrics_router",
    "websocket_router",
    "learning_router",
    "speech_router",
    "feedback_router",
    "optimize_router",
]
