"""Tests for the async-to-sync token bridge.

The chat REPL is synchronous and spends most of a voice turn blocked inside
audio playback, while ``InferenceEngine.stream`` is an async generator.
Consuming the stream on a background thread is what lets the two overlap:
generation of the next sentence continues while the current one is being
spoken. Awaiting it inline would serialise them again.
"""

from __future__ import annotations

import threading
import time

import pytest

from nira.speech.pipeline import iter_engine_tokens


class _Engine:
    """Minimal engine exposing the async stream() the bridge consumes."""

    def __init__(self, tokens, *, fail_after=None, delay=0.0):
        self._tokens = tokens
        self._fail_after = fail_after
        self._delay = delay
        self.calls = []
        self.produced = 0

    async def stream(self, messages, *, model, **kwargs):
        self.calls.append({"messages": messages, "model": model, **kwargs})
        for index, token in enumerate(self._tokens):
            if self._fail_after is not None and index == self._fail_after:
                raise RuntimeError("engine exploded")
            if self._delay:
                await _sleep(self._delay)
            self.produced += 1
            yield token


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)


class TestTokenDelivery:
    def test_yields_every_token_in_order(self) -> None:
        engine = _Engine(["Hel", "lo ", "world"])

        assert list(iter_engine_tokens(engine, [], model="m")) == [
            "Hel",
            "lo ",
            "world",
        ]

    def test_empty_stream_yields_nothing(self) -> None:
        assert list(iter_engine_tokens(_Engine([]), [], model="m")) == []

    def test_passes_messages_model_and_kwargs_through(self) -> None:
        engine = _Engine(["x"])
        messages = [{"role": "user", "content": "hi"}]

        list(iter_engine_tokens(engine, messages, model="qwen", temperature=0.2))

        assert engine.calls[0]["messages"] == messages
        assert engine.calls[0]["model"] == "qwen"
        assert engine.calls[0]["temperature"] == 0.2

    def test_join_timeout_is_not_forwarded_to_the_engine(self) -> None:
        """It configures the bridge, not the completion."""
        engine = _Engine(["x"])

        list(iter_engine_tokens(engine, [], model="m", join_timeout=1.0))

        assert "join_timeout" not in engine.calls[0]


class TestErrors:
    def test_a_mid_stream_failure_reaches_the_caller(self) -> None:
        """Swallowing it would silently truncate the reply instead."""
        engine = _Engine(["one ", "two ", "three"], fail_after=2)

        received = []
        with pytest.raises(RuntimeError, match="engine exploded"):
            for token in iter_engine_tokens(engine, [], model="m"):
                received.append(token)

        assert received == ["one ", "two "]


class TestConcurrency:
    def test_generation_continues_while_the_consumer_is_blocked(self) -> None:
        """The whole reason for the background thread.

        A consumer that stalls (as playback does) must not stall the engine;
        otherwise sentence N+1 only starts generating once sentence N has
        finished being spoken, which is the serialisation this replaces.
        """
        engine = _Engine([f"t{i}" for i in range(12)])

        stream = iter_engine_tokens(engine, [], model="m")
        first = next(stream)
        assert first == "t0"

        # Stand in for playback: block without touching the stream.
        time.sleep(0.4)
        produced_while_blocked = engine.produced

        rest = list(stream)

        assert produced_while_blocked > 1, (
            "engine did not run ahead while the consumer was blocked"
        )
        assert [first, *rest] == [f"t{i}" for i in range(12)]

    def test_abandoning_the_iterator_stops_the_producer(self) -> None:
        """Otherwise the thread keeps filling a queue nobody reads."""
        engine = _Engine([f"t{i}" for i in range(500)], delay=0.002)

        before = threading.active_count()
        stream = iter_engine_tokens(engine, [], model="m")
        next(stream)
        stream.close()

        deadline = time.monotonic() + 5.0
        while threading.active_count() > before and time.monotonic() < deadline:
            time.sleep(0.02)

        assert threading.active_count() <= before, "producer thread outlived consumer"

    def test_worker_does_not_outlive_a_completed_stream(self) -> None:
        before = threading.active_count()

        list(iter_engine_tokens(_Engine(["a", "b"]), [], model="m"))

        deadline = time.monotonic() + 5.0
        while threading.active_count() > before and time.monotonic() < deadline:
            time.sleep(0.02)

        assert threading.active_count() <= before
