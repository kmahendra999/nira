"""Runnable entry point for the gateway daemon.

``python -m nira.daemon`` (and ``-m nira.daemon.gateway``, which delegates here)
is what the generated systemd unit and launchd plist supervise. Before this
existed those units pointed at a module with no ``__main__`` block, so the
process imported it and exited 0 immediately: systemd saw a clean exit and did
not restart it, launchd's ``KeepAlive`` respawned it in a loop, and
``nira gateway status`` reported success either way.

Blocks until SIGTERM or SIGINT, then shuts the daemon down, so a service
manager can stop it cleanly rather than having to kill it.
"""

from __future__ import annotations

import logging
import signal
import sys
from types import FrameType
from typing import Optional

from nira.daemon.gateway import GatewayDaemon

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    daemon = GatewayDaemon()

    def _handle_signal(signum: int, _frame: Optional[FrameType]) -> None:
        logger.info("Received %s, shutting down", signal.Signals(signum).name)
        # Release run_forever's wait; its finally clause performs the shutdown.
        daemon.stop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _handle_signal)

    try:
        daemon.run_forever()
    except Exception:
        logger.exception("Gateway daemon exited with an error")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
