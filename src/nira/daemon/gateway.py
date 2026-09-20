from __future__ import annotations

import logging
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)


class GatewayDaemon:
    """Composes channels, sessions, agents, and scheduler into a daemon."""

    def __init__(
        self,
        config: Any = None,
        session_store: Any = None,
        agent_manager: Any = None,
        agent_scheduler: Any = None,
        event_bus: Any = None,
    ) -> None:
        self._config = config
        self._session_store = session_store
        self._agent_manager = agent_manager
        self._agent_scheduler = agent_scheduler
        self._event_bus = event_bus
        self._running = False
        self._stop_event = threading.Event()

    @staticmethod
    def session_key(
        platform: str,
        chat_type: str,
        chat_id: str,
        thread_id: Optional[str],
    ) -> str:
        return f"agent:main:{platform}:{chat_type}:{chat_id}:{thread_id}"

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        """Bring the daemon's components up. Returns once they are running."""
        if self._running:
            return
        self._stop_event.clear()
        if self._agent_scheduler is not None:
            self._agent_scheduler.start()
        self._running = True
        logger.info("Gateway daemon started")

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Block until :meth:`stop` is called. True if stopped, False on timeout."""
        return self._stop_event.wait(timeout)

    def stop(self) -> None:
        """Take the daemon's components down and release :meth:`wait`.

        Idempotent: a signal handler and ``run_forever``'s cleanup both call
        this, and shutting a component down twice is not safe in general.
        """
        already_stopped = self._stop_event.is_set()
        self._stop_event.set()
        if already_stopped:
            return
        self._running = False
        if self._agent_scheduler is not None:
            self._agent_scheduler.stop()
        logger.info("Gateway daemon stopped")

    def run_forever(self) -> None:
        """Start, then block until stopped.

        This is what a service manager supervises. Without it the module had no
        runnable entry point at all, so the generated systemd and launchd units
        pointed at ``python -m nira.daemon.gateway``, which imported the module
        and exited 0 — systemd then treated the service as cleanly finished
        (``Restart=on-failure`` does not fire on 0), while launchd's
        ``KeepAlive`` respawned it forever. Both reported a healthy gateway that
        had never run.
        """
        self.start()
        try:
            self.wait()
        finally:
            self.stop()


if __name__ == "__main__":  # pragma: no cover - delegates to nira.daemon.__main__
    # Units generated before nira.daemon gained a __main__ invoke this module
    # directly; keep that path runnable rather than silently exiting 0.
    import sys

    from nira.daemon.__main__ import main

    sys.exit(main())
