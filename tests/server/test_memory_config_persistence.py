"""The memory settings the UI shows must be the ones the server is in.

Before this, the Settings panel kept the memory toggle in ``localStorage`` and
defaulted it to ON, while ``[memory] enabled`` in ``config.toml`` defaulted to
off — so the switch reported a state the server was never in, and moving it
changed nothing. These tests pin both halves of the fix: the server reports its
real state, and a write to it lands in the config file.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from nira.core.config import load_config
from nira.core.config_writer import read_config_document, update_config_section


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text(
        '# hand-written, and it stays that way\n[engine]\ndefault = "ollama"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("NIRA_CONFIG", str(path))
    return path


@pytest.fixture
def client(config_file):
    from nira.server.app import create_app

    config = load_config()
    app = create_app(engine=None, model="test-model", config=config)
    app.state.config = config
    with TestClient(app) as test_client:
        yield test_client


def test_stats_reports_whether_memory_is_enabled(client):
    body = client.get("/v1/memory/stats").json()
    assert "enabled" in body, "the UI cannot show the truth if stats never says it"
    assert body["enabled"] is False


def test_config_get_reports_enabled(client):
    body = client.get("/v1/memory/config").json()
    assert body["enabled"] is False


def test_put_config_persists_to_disk(client, config_file):
    resp = client.put("/v1/memory/config", json={"enabled": True, "context_top_k": 9})
    assert resp.status_code == 200, resp.text
    assert resp.json()["enabled"] is True

    doc = read_config_document(config_file)
    assert doc["memory"]["enabled"] is True
    assert doc["memory"]["context_top_k"] == 9

    # A fresh load — the restart the user would do — sees the same thing.
    assert load_config().memory.enabled is True

    # And the reported state changes with it.
    assert client.get("/v1/memory/stats").json()["enabled"] is True


def test_put_config_applies_without_restart(client):
    client.put("/v1/memory/config", json={"context_max_tokens": 4096})
    assert client.get("/v1/memory/config").json()["context_max_tokens"] == 4096


def test_context_from_memory_goes_to_the_agent_table(client, config_file):
    client.put("/v1/memory/config", json={"context_from_memory": True})
    doc = read_config_document(config_file)
    assert doc["agent"]["context_from_memory"] is True
    assert "context_from_memory" not in doc.get("memory", {})


def test_omitted_fields_are_left_alone(client, config_file):
    client.put("/v1/memory/config", json={"enabled": True, "context_top_k": 3})
    client.put("/v1/memory/config", json={"context_top_k": 4})
    doc = read_config_document(config_file)
    assert doc["memory"]["enabled"] is True, "a partial update must not reset the rest"
    assert doc["memory"]["context_top_k"] == 4


@pytest.mark.parametrize(
    "payload",
    [
        {"context_top_k": -1},
        {"context_max_tokens": -5},
        {"context_min_score": 1.5},
        {"context_min_score": -0.1},
    ],
)
def test_out_of_range_values_are_rejected(client, payload):
    assert client.put("/v1/memory/config", json=payload).status_code == 422


def test_writing_config_keeps_comments_and_other_sections(config_file):
    update_config_section("memory", {"enabled": True})
    text = config_file.read_text(encoding="utf-8")
    assert "# hand-written, and it stays that way" in text
    assert 'default = "ollama"' in text


def test_writing_config_is_atomic_on_failure(config_file, monkeypatch):
    original = config_file.read_text(encoding="utf-8")
    import os as os_mod

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os_mod, "replace", boom)
    with pytest.raises(OSError):
        update_config_section("memory", {"enabled": True})
    assert config_file.read_text(encoding="utf-8") == original
    leftovers = [p for p in config_file.parent.iterdir() if p.name.endswith(".tmp")]
    assert not leftovers, f"temp file left behind: {leftovers}"


def test_none_removes_a_key(config_file):
    update_config_section("memory", {"context_top_k": 7})
    update_config_section("memory", {"context_top_k": None})
    assert "context_top_k" not in read_config_document(config_file).get("memory", {})


class _FakeService:
    """Stands in for the background fact-extraction service.

    ``is_running`` is a *property* here because it is one on the real
    ``MemoryService``. An earlier fake declared it as a method, so the stats
    endpoint's ``service.is_running()`` passed the test and raised
    ``TypeError: 'bool' object is not callable`` against the real server —
    where, because both reads shared one ``try``, it silently reported no
    memory service at all on a server that was actively remembering.
    """

    def __init__(self, count: int = 3, running: bool = True, boom: bool = False):
        self._count = count
        self._running = running
        self._boom = boom

    def fact_count(self) -> int:
        if self._boom:
            raise RuntimeError("fact store is locked")
        return self._count

    @property
    def is_running(self) -> bool:
        return self._running


class _FakeServiceWithMethod(_FakeService):
    """Some backends may expose it as a method; both must work."""

    @property
    def is_running(self):  # type: ignore[override]
        return lambda: self._running


def test_stats_reports_facts_learned(client):
    client.app.state.memory_service = _FakeService(count=7)
    body = client.get("/v1/memory/stats").json()
    assert body["facts"] == 7
    assert body["service_running"] is True


def test_stats_without_a_service_says_so(client):
    client.app.state.memory_service = None
    body = client.get("/v1/memory/stats").json()
    assert body["facts"] is None
    assert body["service_running"] is None


def test_a_locked_fact_store_does_not_500_the_stats_call(client):
    client.app.state.memory_service = _FakeService(boom=True)
    resp = client.get("/v1/memory/stats")
    assert resp.status_code == 200, "stats must survive a mid-write fact store"
    assert resp.json()["facts"] is None


def test_unavailable_backend_is_refused_with_a_reason(client, monkeypatch):
    from nira.server import api_routes

    monkeypatch.setattr(
        api_routes,
        "_available_backends",
        lambda: [{"id": "faiss", "available": False, "missing": ["faiss"]}],
    )
    resp = client.put("/v1/memory/config", json={"default_backend": "faiss"})
    assert resp.status_code == 422
    assert "faiss" in resp.json()["detail"]


def test_unknown_backend_is_refused(client):
    resp = client.put("/v1/memory/config", json={"default_backend": "nonsense"})
    assert resp.status_code == 422


def test_a_locked_fact_store_still_reports_the_service_as_running(client):
    client.app.state.memory_service = _FakeService(boom=True, running=True)
    body = client.get("/v1/memory/stats").json()
    assert body["facts"] is None
    assert body["service_running"] is True, "one failing read must not blank the other"


def test_is_running_as_a_method_also_works(client):
    client.app.state.memory_service = _FakeServiceWithMethod(count=2, running=True)
    body = client.get("/v1/memory/stats").json()
    assert body["facts"] == 2
    assert body["service_running"] is True


def test_the_real_service_exposes_is_running_as_a_property():
    """Pin the shape the endpoint reads, so a refactor there fails here."""
    from nira.memory.service import MemoryService

    assert isinstance(MemoryService.__dict__["is_running"], property), (
        "the stats endpoint handles both, but this is the shape it was written for"
    )


def test_writing_invalidates_the_cached_config(config_file):
    """A write the writing process cannot see is worse than no write.

    ``load_config`` is lru_cached, so before this the process that wrote the
    file kept reading the values it had just replaced.
    """
    from nira.core.config import load_config

    assert load_config().network.mode == "auto"
    update_config_section("network", {"mode": "lan"})
    assert load_config().network.mode == "lan"
