"""The HTTP surface for generation.

Backed by a fake runner rather than a real pipeline: these tests are about
the contract — a job id returned immediately, progress polled, cancellation,
and a result endpoint that cannot be turned into a file-read primitive.
Loading Stable Diffusion to check any of that would take minutes and prove
none of it.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from nira.generate.jobs import JobKind, JobStatus


def start(client, prompt: str = "a cat") -> str:
    """Queue an image job and return its id."""
    response = client.post("/v1/generate/image", json={"prompt": prompt})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def gen_queue(tmp_path, monkeypatch):
    """The queue the routes use, so tests can inspect real Job objects."""
    from nira.generate import jobs as jobs_module

    monkeypatch.setattr(jobs_module, "output_dir", lambda: tmp_path)
    queue = jobs_module.JobQueue()
    yield queue
    queue.shutdown()


@pytest.fixture
def client(tmp_path, monkeypatch, gen_queue):
    """A server whose generation queue runs a fake, instant backend."""
    from nira.server import api_routes

    monkeypatch.setattr(
        api_routes, "_generation_queue", lambda: gen_queue, raising=False
    )

    def fake_image(job, report):
        report(0.5, "Halfway")
        path = tmp_path / f"{job.id}.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\n")
        return path.name

    gen_queue.register(JobKind.IMAGE, fake_image)

    from nira.server.app import create_app

    app = create_app(engine=None, model="test-model")
    with TestClient(app) as test_client:
        yield test_client


class TestStarting:
    def test_a_job_is_accepted_and_returns_immediately(self, client):
        response = client.post("/v1/generate/image", json={"prompt": "a cat"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["id"]
        assert body["kind"] == "image"
        assert body["status"] in {"queued", "running", "done"}

    def test_an_empty_prompt_is_refused(self, client):
        response = client.post("/v1/generate/image", json={"prompt": "   "})
        assert response.status_code == 422

    def test_an_unknown_kind_is_404_with_the_options_named(self, client):
        response = client.post("/v1/generate/hologram", json={"prompt": "a cat"})
        assert response.status_code == 404
        assert "image" in response.json()["detail"]

    def test_an_unavailable_backend_says_what_to_install(self, client):
        # video is registered nowhere in this fixture, which is exactly the
        # shape of an install without the `generate` extra.
        response = client.post("/v1/generate/video", json={"prompt": "a cat"})
        assert response.status_code == 501
        assert "not available" in response.json()["detail"]


class TestPolling:
    def test_a_job_can_be_polled_to_completion(self, client):
        job_id = start(client)

        assert wait_for(
            lambda: client.get(f"/v1/generate/jobs/{job_id}").json()["status"] == "done"
        )
        body = client.get(f"/v1/generate/jobs/{job_id}").json()
        assert body["result"].endswith(".png")
        assert body["progress"] == 1.0
        assert body["elapsed_seconds"] is not None

    def test_an_unknown_job_is_404(self, client):
        assert client.get("/v1/generate/jobs/nope").status_code == 404

    def test_jobs_are_listed_newest_first(self, client):
        first = start(client, "one")
        second = start(client, "two")
        assert wait_for(
            lambda: client.get(f"/v1/generate/jobs/{second}").json()["status"] == "done"
        )
        listed = [j["id"] for j in client.get("/v1/generate/jobs").json()["jobs"]]
        assert listed.index(second) < listed.index(first)


class TestCancelling:
    def test_cancelling_a_finished_job_is_refused(self, client):
        job_id = start(client)
        assert wait_for(
            lambda: client.get(f"/v1/generate/jobs/{job_id}").json()["status"] == "done"
        )
        assert client.delete(f"/v1/generate/jobs/{job_id}").status_code == 409

    def test_cancelling_an_unknown_job_is_refused(self, client):
        assert client.delete("/v1/generate/jobs/nope").status_code == 409


class TestResult:
    def test_the_finished_file_is_served(self, client):
        job_id = start(client)
        assert wait_for(
            lambda: client.get(f"/v1/generate/jobs/{job_id}").json()["status"] == "done"
        )
        response = client.get(f"/v1/generate/jobs/{job_id}/result")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/png")
        assert response.content.startswith(b"\x89PNG")

    def test_a_running_job_has_no_result_yet(self, client, gen_queue):
        # 409, not 404: the job exists and is working. Saying "not found"
        # about a job the user is watching would read as a crash.
        import threading

        blocker = threading.Event()
        gen_queue.register(
            JobKind.IMAGE, lambda job, report: blocker.wait(3) and "x.png"
        )
        job_id = start(client)
        assert wait_for(
            lambda: client.get(f"/v1/generate/jobs/{job_id}").json()["status"]
            == "running"
        )

        response = client.get(f"/v1/generate/jobs/{job_id}/result")
        assert response.status_code == 409
        assert "running" in response.json()["detail"]
        blocker.set()

    def test_a_result_path_cannot_escape_the_output_directory(
        self, client, gen_queue, tmp_path
    ):
        # The filename comes from a backend and the id from a URL. Neither may
        # become a way to read a file outside the output directory.
        secret = tmp_path.parent / "outside.txt"
        secret.write_text("not yours")

        job_id = start(client)
        assert wait_for(
            lambda: client.get(f"/v1/generate/jobs/{job_id}").json()["status"] == "done"
        )

        job = gen_queue.get(job_id)
        assert job is not None, "the test must reach the real job to be meaningful"
        job.result = "../outside.txt"

        response = client.get(f"/v1/generate/jobs/{job_id}/result")
        assert response.status_code == 404
        assert b"not yours" not in response.content


class TestCapabilities:
    def test_capabilities_names_each_kind(self, client):
        body = client.get("/v1/generate/capabilities").json()
        for kind in ("image", "audio", "video"):
            assert kind in body
            assert "available" in body[kind]

    def test_an_unavailable_kind_explains_itself(self, client, monkeypatch):
        from nira.generate import video

        monkeypatch.setattr(video, "available", lambda: False)
        monkeypatch.setattr(video, "why", lambda: "needs torch and diffusers")

        body = client.get("/v1/generate/capabilities").json()
        assert body["video"]["available"] is False
        # The UI shows this instead of a button that fails.
        assert "torch" in body["video"]["reason"]


class TestJobStatusEnum:
    def test_every_status_is_a_plain_string_on_the_wire(self):
        # The UI switches on these; an enum repr leaking through would break
        # every comparison silently.
        for status in JobStatus:
            assert isinstance(status.value, str)
