"""Bridge an engine's async token stream into a blocking caller.

``InferenceEngine.stream`` is an async generator; the chat REPL is synchronous
and spends most of a voice turn blocked inside audio playback. Consuming the
stream on a background thread and handing tokens over a queue is what makes the
two overlap: while the main thread is playing sentence N, the producer keeps
pulling sentence N+1 off the wire. Awaiting the stream inline would serialise
them again and give back everything the segmentation bought.

The queue is deliberately unbounded. Running ahead of playback is the point —
generation is usually faster than speech, and a bounded queue would throttle the
model to the speed of the speaker.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
from typing import Any, Iterator, Sequence

logger = logging.getLogger(__name__)

_TOKEN = "token"
_ERROR = "error"
_DONE = "done"


def iter_engine_tokens(
    engine: Any,
    messages: Sequence[Any],
    *,
    model: str,
    join_timeout: float = 5.0,
    **kwargs: Any,
) -> Iterator[str]:
    """Yield tokens from ``engine.stream`` as they arrive.

    Exceptions raised inside the stream surface to the caller, at the point the
    failing token would have been yielded, so a mid-stream engine error is not
    silently truncated into a short reply.

    Abandoning the iterator early (``break``, or an exception in the consumer)
    signals the producer to stop rather than leaving it filling a queue nobody
    reads.
    """
    channel: queue.Queue = queue.Queue()
    cancelled = threading.Event()

    async def _produce() -> None:
        try:
            async for token in engine.stream(messages, model=model, **kwargs):
                if cancelled.is_set():
                    return
                channel.put((_TOKEN, token))
        except Exception as exc:  # noqa: BLE001 - re-raised on the consumer
            channel.put((_ERROR, exc))
        else:
            channel.put((_DONE, None))

    def _run() -> None:
        try:
            asyncio.run(_produce())
        except Exception as exc:  # noqa: BLE001 - loop setup/teardown failure
            channel.put((_ERROR, exc))
        finally:
            # A cancelled producer never reaches the _DONE above; unblock any
            # consumer still waiting on the queue.
            if cancelled.is_set():
                channel.put((_DONE, None))

    worker = threading.Thread(target=_run, name="nira-token-stream", daemon=True)
    worker.start()

    try:
        while True:
            kind, payload = channel.get()
            if kind == _TOKEN:
                yield payload
            elif kind == _ERROR:
                raise payload
            else:
                return
    finally:
        cancelled.set()
        worker.join(timeout=join_timeout)
        if worker.is_alive():
            # Daemon thread, so it cannot keep the process alive; log rather
            # than block the user's REPL waiting for a wedged HTTP read.
            logger.debug("token stream worker did not stop within %ss", join_timeout)


__all__ = ["iter_engine_tokens"]
