"""Generating images, audio and video locally.

Every backend here runs on the CPU, because that is what this machine has.
That constraint drives every model choice: distilled few-step models over
their full-step originals, small over large, and an honest estimate of the
wait rather than a spinner.

Work is queued rather than served synchronously — see :mod:`nira.generate.jobs`
for why — and each backend reports progress and checks for cancellation
between steps.
"""

from nira.generate.jobs import Job, JobKind, JobQueue, JobStatus, get_queue, output_dir

__all__ = [
    "Job",
    "JobKind",
    "JobQueue",
    "JobStatus",
    "get_queue",
    "output_dir",
]
