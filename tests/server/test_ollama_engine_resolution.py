"""Finding Ollama behind the wrappers.

`POST /v1/models/pull` guarded on `engine_name != "ollama" and
engine.engine_id != "ollama"`. Both are false on a normal install: the engine
is wrapped by InstrumentedEngine for telemetry and GuardrailsEngine for
safety, and as soon as a second backend is discovered it is wrapped again by
MultiEngine — at which point `engine_name` becomes "multi".

So the check refused to pull on exactly the machines where Ollama was present
and working, with a 501 saying pulling is "only supported with the Ollama
engine" to a user who was running Ollama.
"""

from __future__ import annotations

from nira.server.routes import _ollama_engine


class FakeOllama:
    engine_id = "ollama"
    _host = "http://localhost:11434"


class FakeVllm:
    engine_id = "vllm"


class TestBareEngine:
    def test_finds_ollama(self) -> None:
        engine = FakeOllama()
        assert _ollama_engine(engine) is engine

    def test_returns_none_for_another_engine(self) -> None:
        assert _ollama_engine(FakeVllm()) is None

    def test_handles_none(self) -> None:
        assert _ollama_engine(None) is None


class TestThroughWrappers:
    def test_through_instrumented(self) -> None:
        from nira.telemetry.instrumented_engine import InstrumentedEngine

        inner = FakeOllama()
        wrapped = object.__new__(InstrumentedEngine)
        wrapped._inner = inner

        assert _ollama_engine(wrapped) is inner

    def test_through_multi(self) -> None:
        from nira.engine.multi import MultiEngine

        inner = FakeOllama()
        multi = object.__new__(MultiEngine)
        multi._engines = [("vllm", FakeVllm()), ("ollama", inner)]

        # The configuration that produced the bug: engine_name is "multi".
        assert _ollama_engine(multi) is inner

    def test_through_multi_and_instrumented(self) -> None:
        from nira.engine.multi import MultiEngine
        from nira.telemetry.instrumented_engine import InstrumentedEngine

        inner = FakeOllama()
        instrumented = object.__new__(InstrumentedEngine)
        instrumented._inner = inner
        multi = object.__new__(MultiEngine)
        multi._engines = [("ollama", instrumented)]

        assert _ollama_engine(multi) is inner

    def test_multi_without_ollama_is_none(self) -> None:
        from nira.engine.multi import MultiEngine

        multi = object.__new__(MultiEngine)
        multi._engines = [("vllm", FakeVllm())]

        # Still a genuine 501: there is no Ollama to pull with.
        assert _ollama_engine(multi) is None

    def test_the_host_survives_unwrapping(self) -> None:
        """The handler reads `_host` off whatever this returns."""
        from nira.engine.multi import MultiEngine

        inner = FakeOllama()
        inner._host = "http://127.0.0.1:11434"
        multi = object.__new__(MultiEngine)
        multi._engines = [("ollama", inner)]

        assert getattr(_ollama_engine(multi), "_host") == "http://127.0.0.1:11434"
