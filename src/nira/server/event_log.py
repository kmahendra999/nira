"""A short, sequenced history of forwarded events, for reconnecting clients.

The agent-events WebSocket was live-only: no sequence numbers, no replay, and
a bounded per-client queue that silently drops when a consumer falls behind. On
a desktop that is invisible. On a phone it is the normal case — every cell
handover, every screen lock, every walk out of Wi-Fi range drops the socket,
and each reconnect silently loses whatever happened in the gap. Progress would
appear to stall mid-task with nothing to say it had.

This keeps the last N events with monotonic sequence numbers so a client can
reconnect with ``?since=<seq>`` and be handed the difference.

Memory, not disk, and deliberately so: the point is to survive a reconnect
measured in seconds, not to be a durable record. Traces already persist to
SQLite for that.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Any, Deque, Dict, List, Tuple

# ~2 minutes of a busy agent run. Large enough to cover a tunnel drop or a
# backgrounded app, small enough to stay cheap for every connected client.
DEFAULT_CAPACITY = 512


class EventLog:
    """Ring buffer of recent events, addressable by sequence number."""

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self._capacity = capacity
        self._events: Deque[Tuple[int, Dict[str, Any]]] = deque(maxlen=capacity)
        self._next_seq = 1
        # Publishing happens on whatever thread raised the event — an agent
        # worker, the scheduler pool — while reads happen on the event loop.
        self._lock = threading.Lock()

    @property
    def latest_seq(self) -> int:
        """Sequence number of the most recent event, or 0 when empty."""
        with self._lock:
            return self._next_seq - 1

    def append(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Record *payload* and return it stamped with its sequence number."""
        with self._lock:
            seq = self._next_seq
            self._next_seq += 1
            stamped = {**payload, "seq": seq}
            self._events.append((seq, stamped))
            return stamped

    def since(self, seq: int) -> Tuple[List[Dict[str, Any]], bool]:
        """Return events after *seq*, and whether any were missed.

        The flag is the honest part. If the requested cursor has already been
        evicted, the client cannot be given a complete history, and silently
        handing it a partial one would look like a complete one. Callers
        surface it so a UI can say "some progress was missed" rather than
        quietly showing a gap.
        """
        with self._lock:
            if not self._events:
                return [], False
            oldest = self._events[0][0]
            # seq 0 means "everything you have"; a cursor at or past the newest
            # event is simply up to date, not a gap.
            gap = seq > 0 and seq < oldest - 1
            missed = seq == 0 and oldest > 1
            return (
                [payload for stored, payload in self._events if stored > seq],
                gap or missed,
            )


__all__ = ["DEFAULT_CAPACITY", "EventLog"]
