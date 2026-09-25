"""A queue for work that takes minutes, or hours.

Generating an image on this hardware takes tens of seconds; a video takes far
longer. Neither fits in an HTTP request, so every generate endpoint returns a
job id immediately and the client polls. That is not a nicety — a synchronous
route would hold a worker, hit every proxy timeout in the path, and give the
user a spinner with no way to tell "still working" from "died".

**One job at a time, on purpose.** Diffusion saturates every core it is given.
Two concurrent jobs each get half the machine and both take twice as long, so
running them serially finishes the first one sooner and the second one at the
same time. A queue is also the only honest way to answer "how long?" — you can
count the jobs ahead of you.
"""

from __future__ import annotations

import logging
import queue
import secrets
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = ["Job", "JobKind", "JobStatus", "JobQueue", "get_queue", "output_dir"]


class JobKind(str, Enum):
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


def output_dir() -> Path:
    """Where generated files land. Outside the repo, beside the other state."""
    from nira.core.config import get_config_dir

    path = get_config_dir() / "generated"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Job:
    id: str
    kind: JobKind
    prompt: str
    params: Dict[str, Any] = field(default_factory=dict)
    status: JobStatus = JobStatus.QUEUED
    #: 0.0 - 1.0 where the backend can report it, else None.
    progress: Optional[float] = None
    #: What the job is doing right now, in words a user can read.
    detail: str = ""
    #: Path to the finished file, relative to output_dir().
    result: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    #: Set by cancel(); backends check it between steps.
    _cancelled: threading.Event = field(
        default_factory=threading.Event, repr=False, compare=False
    )

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def to_public(self) -> Dict[str, Any]:
        elapsed = (
            (self.finished_at or time.time()) - self.started_at
            if self.started_at
            else None
        )
        return {
            "id": self.id,
            "kind": self.kind.value,
            "prompt": self.prompt,
            "status": self.status.value,
            "progress": self.progress,
            "detail": self.detail,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "elapsed_seconds": round(elapsed, 1) if elapsed else None,
        }


#: A backend is called with the job and a progress callback.
Runner = Callable[[Job, Callable[[float, str], None]], str]


class JobQueue:
    """Serial background worker with a bounded, inspectable history."""

    def __init__(self, max_history: int = 100) -> None:
        self._jobs: Dict[str, Job] = {}
        self._order: List[str] = []
        self._pending: "queue.Queue[str]" = queue.Queue()
        self._runners: Dict[JobKind, Runner] = {}
        self._lock = threading.Lock()
        self._max_history = max_history
        self._worker: Optional[threading.Thread] = None
        self._stop = threading.Event()

    # -- registration ------------------------------------------------------

    def register(self, kind: JobKind, runner: Runner) -> None:
        self._runners[kind] = runner

    def supported(self) -> List[str]:
        return sorted(k.value for k in self._runners)

    # -- submission --------------------------------------------------------

    def submit(self, kind: JobKind, prompt: str, **params: Any) -> Job:
        if kind not in self._runners:
            raise ValueError(
                f"{kind.value} generation is not available on this install."
            )
        job = Job(id=secrets.token_urlsafe(9), kind=kind, prompt=prompt, params=params)
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            self._trim_locked()
        self._pending.put(job.id)
        self._ensure_worker()
        return job

    def _trim_locked(self) -> None:
        """Drop the oldest *finished* jobs until the history fits.

        Two things this must not do. It must not drop a job that is still
        queued or running — a client is polling it, and losing it reads as a
        silent failure. And it must not reorder: an earlier version moved an
        unfinished job to the end of the list to skip it, which quietly
        shuffled the history the UI displays.
        """
        over = len(self._order) - self._max_history
        if over <= 0:
            return
        kept: List[str] = []
        for job_id in self._order:
            job = self._jobs.get(job_id)
            finished = job is None or job.status in (
                JobStatus.DONE,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            )
            if over > 0 and finished:
                self._jobs.pop(job_id, None)
                over -= 1
                continue
            kept.append(job_id)
        self._order = kept

    # -- inspection --------------------------------------------------------

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self, limit: int = 50) -> List[Job]:
        with self._lock:
            ids = self._order[-limit:]
            return [self._jobs[i] for i in reversed(ids) if i in self._jobs]

    def position(self, job_id: str) -> int:
        """How many jobs are ahead of this one, or 0 if it is next/running."""
        with self._lock:
            waiting = [
                i
                for i in self._order
                if self._jobs.get(i)
                and self._jobs[i].status is JobStatus.QUEUED
            ]
        return waiting.index(job_id) if job_id in waiting else 0

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job is None or job.status in (
            JobStatus.DONE,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        ):
            return False
        job._cancelled.set()
        if job.status is JobStatus.QUEUED:
            # Never picked up, so mark it now rather than waiting for the
            # worker to reach it.
            job.status = JobStatus.CANCELLED
            job.finished_at = time.time()
        return True

    # -- the worker --------------------------------------------------------

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._stop.clear()
            self._worker = threading.Thread(
                target=self._run_forever, name="nira-generate", daemon=True
            )
            self._worker.start()

    def _run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                job_id = self._pending.get(timeout=1.0)
            except queue.Empty:
                continue
            job = self.get(job_id)
            if job is None or job.cancelled:
                if job is not None and job.status is not JobStatus.CANCELLED:
                    job.status = JobStatus.CANCELLED
                    job.finished_at = time.time()
                continue
            self._run_one(job)

    def _run_one(self, job: Job) -> None:
        job.status = JobStatus.RUNNING
        job.started_at = time.time()
        job.detail = "Starting…"

        def report(progress: float, detail: str = "") -> None:
            job.progress = max(0.0, min(1.0, progress))
            if detail:
                job.detail = detail

        try:
            result = self._runners[job.kind](job, report)
            if job.cancelled:
                job.status = JobStatus.CANCELLED
                job.detail = "Cancelled"
            else:
                job.status = JobStatus.DONE
                job.result = result
                job.progress = 1.0
                job.detail = "Finished"
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            if job.cancelled:
                # Raising is how a backend aborts: the image and video
                # pipelines throw from their step callback, because waiting
                # for a multi-minute step to end would make "stop" useless.
                # Reporting that as a failure would show the user a red error
                # for something they asked for.
                job.status = JobStatus.CANCELLED
                job.detail = "Cancelled"
            else:
                logger.exception("generation job %s failed", job.id)
                job.status = JobStatus.FAILED
                # Shown in the UI, so keep it readable rather than dumping a
                # stack trace the user cannot act on.
                job.error = str(exc) or exc.__class__.__name__
                job.detail = "Failed"
        finally:
            job.finished_at = time.time()
            # Finished jobs are what the history can shed; trimming only at
            # submit time never fired, because the oldest were still queued.
            with self._lock:
                self._trim_locked()

    def shutdown(self) -> None:  # pragma: no cover - process teardown
        self._stop.set()


_QUEUE: Optional[JobQueue] = None
_QUEUE_LOCK = threading.Lock()


def get_queue() -> JobQueue:
    """The process-wide queue, created and populated on first use.

    Backends register lazily so that importing this module does not import
    torch: the server starts in a second today and loading a deep-learning
    stack at import would make every start pay for a feature most runs do not
    use.
    """
    global _QUEUE
    with _QUEUE_LOCK:
        if _QUEUE is None:
            _QUEUE = JobQueue()
            _register_backends(_QUEUE)
        return _QUEUE


def _register_backends(q: JobQueue) -> None:
    from nira.generate import audio, image, video

    for kind, module in (
        (JobKind.IMAGE, image),
        (JobKind.AUDIO, audio),
        (JobKind.VIDEO, video),
    ):
        if module.available():
            q.register(kind, module.run)
        else:
            logger.info("%s generation unavailable: %s", kind.value, module.why())
