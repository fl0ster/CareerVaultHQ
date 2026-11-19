"""``cleanup_old_jobs`` run every ``cleanup_interval_seconds`` (daily), deleting unprotected
jobs and parse results older than ``cleanup_max_age_days`` (see :mod:`app.services.cleanup`).
Runs once at startup.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from rq import Queue

from app.config import Settings, get_settings
from app.scheduler.common import EPOCH, fetch_job, free_job_id, is_active
from app.tasks.cleanup import cleanup_old_jobs

log = logging.getLogger(__name__)

CLEANUP_JOB_ID = "scheduler-cleanup-old-jobs"
"""Fixed RQ job id of the cleanup run; only one can exist in the queue at a time."""
CLEANUP_TIMEOUT = 600


class CleanupScheduler:
    """Enqueues ``cleanup_old_jobs`` every ``cleanup_interval_seconds`` unless one is active.

    ``tick(now)`` returns ``"enqueued"``, ``"active"`` or ``"waiting"``.
    """

    def __init__(self, queue: Queue, settings: Settings | None = None) -> None:
        self.queue = queue
        self.settings = settings or get_settings()
        self.interval = timedelta(seconds=self.settings.cleanup_interval_seconds)
        self.next_run_at: datetime = EPOCH

    def tick(self, now: datetime | None = None) -> str:
        now = now or datetime.now(UTC)
        if now < self.next_run_at:
            return "waiting"

        previous = fetch_job(self.queue, CLEANUP_JOB_ID)
        if is_active(previous):
            return "active"
        free_job_id(previous)

        self._enqueue()
        self.next_run_at = now + self.interval
        log.info("Enqueued cleanup; next one in %s", self.interval)
        return "enqueued"

    def _enqueue(self) -> None:
        max_age = self.settings.cleanup_max_age_days
        self.queue.enqueue(
            cleanup_old_jobs,
            max_age,
            job_id=CLEANUP_JOB_ID,
            job_timeout=CLEANUP_TIMEOUT,
            result_ttl=self.settings.job_result_ttl,
            failure_ttl=self.settings.job_result_ttl,
            description=f"cleanup of jobs older than {max_age} days",
        )
