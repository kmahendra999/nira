"""The queue that carries work too slow for an HTTP request.

Tested with fake runners rather than real models: the queue's job is
scheduling, reporting and cancelling, and a test that loads Stable Diffusion
to check that would take minutes and prove nothing about the queue.
"""

from __future__ import annotations

import threading
import time

import pytest

from nira.generate.jobs import JobKind, JobQueue, JobStatus


def wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def queue():
    q = JobQueue()
    yield q
    q.shutdown()


class TestRunningJobs:
    def test_a_job_runs_and_reports_its_result(self, queue):
        queue.register(JobKind.IMAGE, lambda job, report: "out.png")
        job = queue.submit(JobKind.IMAGE, "a cat")

        assert wait_for(lambda: job.status is JobStatus.DONE), job.status
        assert job.result == "out.png"
        assert job.progress == 1.0

    def test_submission_returns_immediately(self, queue):
        # The whole reason for the queue: a synchronous route would hold a
        # worker for minutes and hit every proxy timeout in the path.
        def slow(job, report):
            time.sleep(0.4)
            return "done.png"

        queue.register(JobKind.IMAGE, slow)
        started = time.time()
        job = queue.submit(JobKind.IMAGE, "a cat")
        assert time.time() - started < 0.2
        assert job.status in (JobStatus.QUEUED, JobStatus.RUNNING)

    def test_progress_reaches_the_job(self, queue):
        def reporting(job, report):
            report(0.5, "Halfway")
            time.sleep(0.2)
            return "x.png"

        queue.register(JobKind.IMAGE, reporting)
        job = queue.submit(JobKind.IMAGE, "a cat")

        assert wait_for(lambda: job.detail == "Halfway")
        assert job.progress == 0.5

    def test_progress_is_clamped(self, queue):
        def silly(job, report):
            report(5.0, "over")
            report(-1.0, "under")
            return "x.png"

        queue.register(JobKind.IMAGE, silly)
        job = queue.submit(JobKind.IMAGE, "a cat")
        assert wait_for(lambda: job.status is JobStatus.DONE)
        assert 0.0 <= (job.progress or 0) <= 1.0


class TestFailure:
    def test_a_failing_job_keeps_its_message(self, queue):
        def boom(job, report):
            raise RuntimeError("the model would not load")

        queue.register(JobKind.IMAGE, boom)
        job = queue.submit(JobKind.IMAGE, "a cat")

        assert wait_for(lambda: job.status is JobStatus.FAILED)
        # Shown in the UI, so it has to read as a sentence rather than a
        # stack trace the user cannot act on.
        assert job.error == "the model would not load"

    def test_a_failure_does_not_stop_the_queue(self, queue):
        def boom(job, report):
            raise RuntimeError("nope")

        queue.register(JobKind.IMAGE, boom)
        queue.register(JobKind.AUDIO, lambda job, report: "fine.wav")

        failed = queue.submit(JobKind.IMAGE, "a")
        after = queue.submit(JobKind.AUDIO, "b")

        assert wait_for(lambda: after.status is JobStatus.DONE), after.status
        assert failed.status is JobStatus.FAILED

    def test_an_exception_with_no_message_still_names_something(self, queue):
        def bare(job, report):
            raise KeyError()

        queue.register(JobKind.IMAGE, bare)
        job = queue.submit(JobKind.IMAGE, "a cat")
        assert wait_for(lambda: job.status is JobStatus.FAILED)
        assert job.error


class TestCancellation:
    def test_a_queued_job_can_be_cancelled_before_it_starts(self, queue):
        blocker = threading.Event()
        queue.register(JobKind.IMAGE, lambda job, report: blocker.wait(2) and "x")

        first = queue.submit(JobKind.IMAGE, "first")
        second = queue.submit(JobKind.IMAGE, "second")

        assert wait_for(lambda: first.status is JobStatus.RUNNING)
        assert queue.cancel(second.id)
        assert second.status is JobStatus.CANCELLED
        blocker.set()

    def test_a_running_job_sees_the_flag(self, queue):
        saw = threading.Event()

        def watchful(job, report):
            for _ in range(200):
                if job.cancelled:
                    saw.set()
                    raise RuntimeError("Cancelled")
                time.sleep(0.01)
            return "x.png"

        queue.register(JobKind.IMAGE, watchful)
        job = queue.submit(JobKind.IMAGE, "a cat")
        assert wait_for(lambda: job.status is JobStatus.RUNNING)

        queue.cancel(job.id)

        assert wait_for(lambda: saw.is_set())
        assert wait_for(lambda: job.status is JobStatus.CANCELLED)

    def test_cancelling_a_finished_job_is_refused(self, queue):
        queue.register(JobKind.IMAGE, lambda job, report: "x.png")
        job = queue.submit(JobKind.IMAGE, "a cat")
        assert wait_for(lambda: job.status is JobStatus.DONE)
        assert not queue.cancel(job.id)

    def test_cancelling_an_unknown_job_is_refused(self, queue):
        assert not queue.cancel("nope")


class TestSerialisation:
    def test_jobs_run_one_at_a_time(self, queue):
        # Diffusion saturates every core. Two at once each get half the
        # machine and both take twice as long.
        concurrent = 0
        peak = 0
        lock = threading.Lock()

        def tracked(job, report):
            nonlocal concurrent, peak
            with lock:
                concurrent += 1
                peak = max(peak, concurrent)
            time.sleep(0.1)
            with lock:
                concurrent -= 1
            return "x.png"

        queue.register(JobKind.IMAGE, tracked)
        jobs = [queue.submit(JobKind.IMAGE, f"job {i}") for i in range(4)]

        assert wait_for(
            lambda: all(j.status is JobStatus.DONE for j in jobs), timeout=10
        )
        assert peak == 1, f"{peak} jobs ran at once"

    def test_queue_position_counts_the_jobs_ahead(self, queue):
        blocker = threading.Event()
        queue.register(JobKind.IMAGE, lambda job, report: blocker.wait(3) and "x")

        first = queue.submit(JobKind.IMAGE, "first")
        assert wait_for(lambda: first.status is JobStatus.RUNNING)
        second = queue.submit(JobKind.IMAGE, "second")
        third = queue.submit(JobKind.IMAGE, "third")

        assert queue.position(second.id) == 0
        assert queue.position(third.id) == 1
        blocker.set()


class TestRegistration:
    def test_an_unregistered_kind_is_refused_with_a_usable_message(self, queue):
        with pytest.raises(ValueError) as excinfo:
            queue.submit(JobKind.VIDEO, "a cat")
        assert "not available" in str(excinfo.value)

    def test_supported_lists_what_is_registered(self, queue):
        queue.register(JobKind.IMAGE, lambda job, report: "x")
        queue.register(JobKind.AUDIO, lambda job, report: "y")
        assert queue.supported() == ["audio", "image"]


class TestHistory:
    def test_old_jobs_are_trimmed(self):
        q = JobQueue(max_history=5)
        q.register(JobKind.IMAGE, lambda job, report: "x.png")
        jobs = [q.submit(JobKind.IMAGE, f"j{i}") for i in range(12)]
        assert wait_for(lambda: all(j.status is JobStatus.DONE for j in jobs), 10)
        assert len(q.list(limit=100)) <= 5
        q.shutdown()

    def test_an_unfinished_job_is_never_trimmed_away(self):
        # A client is polling it; dropping it would read as a silent failure.
        q = JobQueue(max_history=2)
        blocker = threading.Event()
        q.register(JobKind.IMAGE, lambda job, report: blocker.wait(3) and "x")

        running = q.submit(JobKind.IMAGE, "running")
        assert wait_for(lambda: running.status is JobStatus.RUNNING)
        for i in range(6):
            q.submit(JobKind.IMAGE, f"later {i}")

        assert q.get(running.id) is not None
        blocker.set()
        q.shutdown()

    def test_list_is_newest_first(self, queue):
        queue.register(JobKind.IMAGE, lambda job, report: "x.png")
        first = queue.submit(JobKind.IMAGE, "first")
        second = queue.submit(JobKind.IMAGE, "second")
        assert wait_for(lambda: second.status is JobStatus.DONE)
        assert [j.id for j in queue.list()][:2] == [second.id, first.id]


class TestPublicShape:
    def test_elapsed_is_reported_once_it_starts(self, queue):
        queue.register(JobKind.IMAGE, lambda job, report: time.sleep(0.15) or "x.png")
        job = queue.submit(JobKind.IMAGE, "a cat")
        assert wait_for(lambda: job.status is JobStatus.DONE)
        assert job.to_public()["elapsed_seconds"] >= 0.1

    def test_a_queued_job_has_no_elapsed_time(self, queue):
        blocker = threading.Event()
        queue.register(JobKind.IMAGE, lambda job, report: blocker.wait(2) and "x")
        queue.submit(JobKind.IMAGE, "first")
        waiting = queue.submit(JobKind.IMAGE, "second")
        assert waiting.to_public()["elapsed_seconds"] is None
        blocker.set()
