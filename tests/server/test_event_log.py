"""Recent-event history, so a reconnecting client can catch up.

The agent-events WebSocket was live-only: no sequence numbers, no replay, and
a bounded per-client queue that drops silently when a consumer falls behind.
On a desktop that is invisible. On a phone it is the normal case — every cell
handover, screen lock or walk out of Wi-Fi range drops the socket, and each
reconnect lost whatever happened in the gap. Progress appeared to stall with
nothing to say it had.
"""

from __future__ import annotations

import pytest

from nira.server.event_log import EventLog


def _event(name: str) -> dict:
    return {"type": name, "timestamp": 0.0, "data": {}}


class TestSequencing:
    def test_sequence_numbers_start_at_one_and_increase(self) -> None:
        log = EventLog()

        assert log.append(_event("a"))["seq"] == 1
        assert log.append(_event("b"))["seq"] == 2

    def test_the_original_payload_is_preserved(self) -> None:
        log = EventLog()

        stamped = log.append({"type": "tool_call_start", "data": {"tool": "Read"}})

        assert stamped["type"] == "tool_call_start"
        assert stamped["data"] == {"tool": "Read"}

    def test_latest_seq_is_zero_when_empty(self) -> None:
        assert EventLog().latest_seq == 0

    def test_latest_seq_tracks_the_newest_event(self) -> None:
        log = EventLog()
        log.append(_event("a"))
        log.append(_event("b"))

        assert log.latest_seq == 2

    def test_capacity_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            EventLog(capacity=0)


class TestReplay:
    def test_returns_only_events_after_the_cursor(self) -> None:
        log = EventLog()
        for name in "abc":
            log.append(_event(name))

        missed, _ = log.since(1)

        assert [event["type"] for event in missed] == ["b", "c"]

    def test_a_current_cursor_returns_nothing(self) -> None:
        log = EventLog()
        log.append(_event("a"))

        assert log.since(1) == ([], False)

    def test_cursor_zero_returns_everything_held(self) -> None:
        log = EventLog()
        for name in "ab":
            log.append(_event(name))

        missed, gap = log.since(0)

        assert [event["type"] for event in missed] == ["a", "b"]
        assert gap is False

    def test_an_empty_log_replays_nothing(self) -> None:
        assert EventLog().since(0) == ([], False)


class TestGapReporting:
    """Whether the backlog is complete is the part a client cannot infer."""

    def test_an_evicted_cursor_is_reported_as_a_gap(self) -> None:
        """Handing back a partial history without saying so would render as a
        complete one."""
        log = EventLog(capacity=3)
        for name in "abcdef":
            log.append(_event(name))

        missed, gap = log.since(1)

        assert gap is True
        assert len(missed) == 3

    def test_a_cursor_still_in_the_buffer_is_not_a_gap(self) -> None:
        log = EventLog(capacity=5)
        for name in "abcd":
            log.append(_event(name))

        _, gap = log.since(2)

        assert gap is False

    def test_cursor_zero_on_a_wrapped_log_is_a_gap(self) -> None:
        """ "Give me everything" cannot be satisfied once events have aged out."""
        log = EventLog(capacity=2)
        for name in "abcd":
            log.append(_event(name))

        _, gap = log.since(0)

        assert gap is True

    def test_the_oldest_retained_cursor_is_not_a_gap(self) -> None:
        log = EventLog(capacity=3)
        for name in "abcde":
            log.append(_event(name))

        # 'c' is the oldest retained event (seq 3); a client at seq 2 has
        # everything that follows.
        _, gap = log.since(2)

        assert gap is False


class TestBounded:
    def test_old_events_are_evicted(self) -> None:
        """In memory on purpose: this survives a reconnect, it is not the
        durable record. Traces already persist to SQLite for that."""
        log = EventLog(capacity=2)
        for name in "abcd":
            log.append(_event(name))

        missed, _ = log.since(0)

        assert [event["type"] for event in missed] == ["c", "d"]


class TestThreadSafety:
    def test_concurrent_appends_produce_unique_sequence_numbers(self) -> None:
        """Events are raised on agent workers and the scheduler pool while
        reads happen on the event loop."""
        import threading

        log = EventLog(capacity=1000)
        seqs: list[int] = []
        lock = threading.Lock()

        def _writer() -> None:
            for _ in range(50):
                stamped = log.append(_event("x"))
                with lock:
                    seqs.append(stamped["seq"])

        threads = [threading.Thread(target=_writer) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert len(seqs) == 400
        assert len(set(seqs)) == 400, "sequence numbers were reused"
