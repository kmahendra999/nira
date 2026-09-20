"""Starting work on a project over HTTP.

The registry and the agent's ``workspace`` both existed; nothing joined them
outside a shell on the machine itself. These tests cover the join, and the
two things that make it safe to expose: the run must not block the caller, and
the caller must not get to choose the agent's posture.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nira.projects import ProjectStore
from nira.server.project_routes import ProjectRun, RunRegistry, projects_router


class FakeAgent:
    """Records how it was built and blocks until released."""

    built: list[dict] = []

    def __init__(self, *args, **kwargs) -> None:
        self.kwargs = kwargs
        FakeAgent.built.append(kwargs)
        self.started = threading.Event()
        self.release = threading.Event()

    def run(self, prompt: str):  # noqa: ANN201
        self.started.set()
        self.release.wait(timeout=5)
        return SimpleNamespace(content=f"did: {prompt}", turns=3, metadata={})


@pytest.fixture
def client(tmp_path, monkeypatch):
    FakeAgent.built = []
    agents: list[FakeAgent] = []

    def _make(*args, **kwargs):
        agent = FakeAgent(*args, **kwargs)
        agents.append(agent)
        return agent

    monkeypatch.setattr("nira.agents.claude_code.ClaudeCodeAgent", _make)

    store = ProjectStore(tmp_path / "projects.db")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    store.add("nira", str(workspace))

    app = FastAPI()
    app.include_router(projects_router)
    app.state.project_store = store
    app.state.engine = object()
    app.state.bus = object()
    app.state.config = SimpleNamespace(
        model=SimpleNamespace(name="claude"),
        agent=SimpleNamespace(permission_mode="acceptEdits"),
    )
    test_client = TestClient(app)
    test_client.agents = agents  # type: ignore[attr-defined]
    test_client.workspace = workspace  # type: ignore[attr-defined]
    test_client.store = store  # type: ignore[attr-defined]
    return test_client


class TestRunRegistry:
    def test_a_run_can_be_read_back(self):
        registry = RunRegistry()
        registry.add(
            ProjectRun(id="run_1", project_id="p", project_name="n", prompt="x")
        )

        assert registry.get("run_1").status == "running"

    def test_finishing_records_the_outcome(self):
        registry = RunRegistry()
        registry.add(
            ProjectRun(id="run_1", project_id="p", project_name="n", prompt="x")
        )

        registry.finish("run_1", status="done", result="ok", turns=4)

        run = registry.get("run_1")
        assert run.status == "done"
        assert run.result == "ok"
        assert run.turns == 4
        assert run.finished_at

    def test_finishing_an_unknown_run_is_not_an_error(self):
        # The run may have been evicted while its thread was still working.
        RunRegistry().finish("run_gone", status="done")

    def test_history_is_bounded(self):
        # A process meant to stay up for weeks cannot keep every run forever.
        registry = RunRegistry(limit=3)
        for index in range(5):
            registry.add(
                ProjectRun(
                    id=f"run_{index}", project_id="p", project_name="n", prompt="x"
                )
            )

        assert registry.get("run_0") is None
        assert registry.get("run_4") is not None
        assert len(registry.list()) == 3

    def test_runs_are_listed_newest_first(self):
        registry = RunRegistry()
        for index in range(3):
            registry.add(
                ProjectRun(
                    id=f"run_{index}", project_id="p", project_name="n", prompt="x"
                )
            )

        assert [run.id for run in registry.list()] == ["run_2", "run_1", "run_0"]

    def test_runs_can_be_filtered_by_project(self):
        registry = RunRegistry()
        registry.add(ProjectRun(id="a", project_id="p1", project_name="n", prompt="x"))
        registry.add(ProjectRun(id="b", project_id="p2", project_name="n", prompt="x"))

        assert [run.id for run in registry.list("p1")] == ["a"]


class TestProjectRoutes:
    def test_projects_can_be_listed(self, client):
        response = client.get("/v1/projects")

        assert response.status_code == 200
        assert [p["name"] for p in response.json()["projects"]] == ["nira"]

    def test_a_project_can_be_fetched_by_name(self, client):
        assert client.get("/v1/projects/nira").status_code == 200

    def test_an_unknown_project_is_a_404(self, client):
        assert client.get("/v1/projects/nope").status_code == 404

    def test_runs_is_not_mistaken_for_a_project_name(self, client):
        # "/{reference}" is a single-segment route; if it were declared first
        # this would look up a project called "runs" and 404.
        response = client.get("/v1/projects/runs")

        assert response.status_code == 200
        assert response.json() == {"runs": []}

    def test_starting_a_run_returns_before_the_work_finishes(self, client):
        response = client.post("/v1/projects/nira/run", json={"prompt": "add a test"})

        assert response.status_code == 200
        run = response.json()["run"]
        assert run["status"] == "running"
        assert run["project_name"] == "nira"

        # The agent is genuinely still working — the request did not wait for
        # it. A phone's radio does not survive a request that blocks for the
        # minutes this takes.
        agent = client.agents[0]
        assert agent.started.wait(timeout=5)
        agent.release.set()

    def test_the_agent_is_rooted_in_the_project_directory(self, client):
        client.post("/v1/projects/nira/run", json={"prompt": "work"})

        # The whole point: the desktop's own agent is rooted wherever the
        # server started, so reusing it would edit the wrong tree.
        assert client.agents[0].kwargs["workspace"] == str(client.workspace)
        client.agents[0].release.set()

    def test_the_caller_cannot_choose_the_permission_mode(self, client):
        client.post(
            "/v1/projects/nira/run",
            json={"prompt": "work", "permission_mode": "bypassPermissions"},
        )

        # Otherwise a device granted only "ask" grants itself the ability to
        # skip every approval the desktop would have raised.
        assert client.agents[0].kwargs["permission_mode"] == "acceptEdits"
        client.agents[0].release.set()

    def test_resource_ceilings_are_clamped(self, client):
        client.post(
            "/v1/projects/nira/run",
            json={"prompt": "work", "timeout": 10_000_000, "max_turns": 99_999},
        )

        assert client.agents[0].kwargs["timeout"] == 7200
        assert client.agents[0].kwargs["max_turns"] == 200
        client.agents[0].release.set()

    def test_nonsense_ceilings_fall_back_to_the_default(self, client):
        client.post(
            "/v1/projects/nira/run",
            json={"prompt": "work", "timeout": "soon", "max_turns": None},
        )

        assert client.agents[0].kwargs["timeout"] == 1800
        assert client.agents[0].kwargs["max_turns"] == 60
        client.agents[0].release.set()

    def test_an_empty_prompt_is_refused(self, client):
        assert (
            client.post("/v1/projects/nira/run", json={"prompt": "   "}).status_code
            == 400
        )

    def test_a_missing_body_is_refused(self, client):
        response = client.post(
            "/v1/projects/nira/run",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400

    def test_a_run_on_an_unknown_project_is_a_404(self, client):
        response = client.post("/v1/projects/nope/run", json={"prompt": "work"})
        assert response.status_code == 404

    def test_a_project_whose_directory_moved_says_so(self, client, tmp_path):
        # The store refuses to register a path that is not a directory, so the
        # only way to reach this state is the way users do: register a real
        # directory, then move or delete it.
        moved = tmp_path / "moved-away"
        moved.mkdir()
        client.store.add("gone", str(moved))
        moved.rmdir()

        response = client.post("/v1/projects/gone/run", json={"prompt": "work"})

        # Otherwise this fails deep inside the Node subprocess, where the
        # reason never reaches the caller.
        assert response.status_code == 409
        assert "not a directory" in response.json()["detail"]

    def test_a_finished_run_reports_its_result(self, client):
        started = client.post("/v1/projects/nira/run", json={"prompt": "add a test"})
        run_id = started.json()["run"]["id"]
        agent = client.agents[0]
        assert agent.started.wait(timeout=5)
        agent.release.set()

        for _ in range(100):
            run = client.get(f"/v1/projects/runs/{run_id}").json()
            if run["status"] != "running":
                break
        assert run["status"] == "done"
        assert run["result"] == "did: add a test"
        assert run["turns"] == 3

    def test_an_unknown_run_is_a_404(self, client):
        assert client.get("/v1/projects/runs/run_nope").status_code == 404

    def test_runs_can_be_filtered_to_one_project(self, client):
        client.post("/v1/projects/nira/run", json={"prompt": "work"})
        client.agents[0].release.set()

        listed = client.get("/v1/projects/runs", params={"project_id": "nope"}).json()
        assert listed["runs"] == []
