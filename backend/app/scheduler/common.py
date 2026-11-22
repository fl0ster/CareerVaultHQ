"""Helpers shared by the scheduled tasks."""

from __future__ import annotations

from datetime import UTC, datetime

from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job, JobStatus

ACTIVE_STATUSES = frozenset({JobStatus.QUEUED, JobStatus.STARTED, JobStatus.DEFERRED, JobStatus.SCHEDULED})
"""RQ statuses meaning a job still occupies its fixed id."""

EPOCH = datetime.min.replace(tzinfo=UTC)
"""Initial ``next_run_at``: due immediately."""


def fetch_job(queue: Queue, job_id: str) -> Job | None:
    """The RQ job stored under ``job_id``, or ``None``."""
    try:
        return Job.fetch(job_id, connection=queue.connection)
    except NoSuchJobError:
        return None


def is_active(job: Job | None) -> bool:
    return job is not None and job.get_status() in ACTIVE_STATUSES


def free_job_id(job: Job | None) -> None:
    """Delete a finished job so its fixed id can be reused; its outcome lives in the DB."""
    if job is not None:
        job.delete()


def aware(value: datetime | None) -> datetime | None:
    """SQLite drops the tzinfo of ``DateTime(timezone=True)``; the stored values are UTC."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
