"""Catch-up ``evaluate_pending_jobs`` run every ``evaluate_interval_seconds``.

It scores parsed jobs the per-parse evaluation (enqueued by ``app.tasks.parse``) missed -
e.g. Redis was down when the parse finished, the evaluation job failed, or a new candidate
profile was generated and every job has to be re-scored. The two never clash: both go
through the same idempotent task, which skips (job, profile) pairs that are already scored,
and the catch-up is enqueued under a fixed RQ job id so a second copy is not queued while
one is still queued or running. If the previous catch-up failed the next one is delayed
with exponential backoff.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from rq import Queue
from rq.job import Job, JobStatus

from app.config import Settings, get_settings
from app.scheduler.common import EPOCH, fetch_job, free_job_id, is_active
from app.tasks.evaluate import evaluate_pending_jobs

log = logging.getLogger(__name__)

EVALUATE_JOB_ID = "scheduler-evaluate-pending-jobs"
"""Fixed RQ job id of the catch-up run; only one can exist in the queue at a time."""
EVALUATE_TIMEOUT = 3600
"""RQ ``job_timeout`` for a catch-up run (``evaluate_batch_size`` OpenRouter calls)."""


class EvaluationScheduler:
    """Enqueues ``evaluate_pending_jobs`` every ``interval`` unless one is already active.

    ``tick(now)`` returns ``"enqueued"``, ``"active"`` or ``"waiting"``.
    """

    def __init__(self, queue: Queue, settings: Settings | None = None) -> None:
        self.queue = queue
        self.settings = settings or get_settings()
        self.interval = timedelta(seconds=self.settings.evaluate_interval_seconds)
        self.max_backoff = timedelta(seconds=self.settings.evaluate_max_backoff_seconds)
        self.next_run_at: datetime = EPOCH
        self.consecutive_failures = 0

    def tick(self, now: datetime | None = None) -> str:
        now = now or datetime.now(UTC)
        if now < self.next_run_at:
            return "waiting"

        previous = fetch_job(self.queue, EVALUATE_JOB_ID)
        if is_active(previous):
            log.info("Catch-up evaluation %s is still %s", previous.id, previous.get_status())
            return "active"

        delay = self._delay_after(previous)
        free_job_id(previous)
        self._enqueue()
        self.next_run_at = now + delay
        self._log_enqueued(delay)
        return "enqueued"

    def _delay_after(self, previous: Job | None) -> timedelta:
        """``interval`` normally; doubled per consecutive failed run, capped."""
        failed = previous is not None and previous.get_status(refresh=False) == JobStatus.FAILED
        self.consecutive_failures = self.consecutive_failures + 1 if failed else 0
        if not self.consecutive_failures:
            return self.interval
        return min(self.interval * 2**self.consecutive_failures, self.max_backoff)

    def _enqueue(self) -> None:
        self.queue.enqueue(
            evaluate_pending_jobs,
            self.settings.evaluate_batch_size,
            job_id=EVALUATE_JOB_ID,
            job_timeout=EVALUATE_TIMEOUT,
            result_ttl=self.settings.job_result_ttl,
            failure_ttl=self.settings.job_result_ttl,
            description="catch-up evaluation of pending jobs",
        )

    def _log_enqueued(self, delay: timedelta) -> None:
        if self.consecutive_failures:
            log.warning(
                "Previous catch-up evaluation failed (%d in a row); next one in %s",
                self.consecutive_failures,
                delay,
            )
        else:
            log.info("Enqueued catch-up evaluation; next one in %s", delay)
