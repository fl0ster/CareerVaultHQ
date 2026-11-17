"""Periodic jobs. Run with ``python -m app.scheduler.scheduler`` (see docker-compose).

The loop wakes up every ``SCHEDULER_SLEEP_SECONDS`` and lets each scheduled task decide
whether it is due. Tasks never run here; they are enqueued on the shared RQ queue and
executed by ``app.workers.worker``.

Currently scheduled:

* :class:`EvaluationScheduler` - a catch-up ``evaluate_pending_jobs`` run every
  ``evaluate_interval_seconds``. It scores parsed jobs the per-parse evaluation (enqueued
  by ``app.tasks.parse``) missed - e.g. Redis was down when the parse finished, the
  evaluation job failed, or a new candidate profile was generated and every job has to be
  re-scored. The two never clash: both go through the same idempotent task, which skips
  (job, profile) pairs that are already scored, and the catch-up is enqueued under a fixed
  RQ job id so a second copy is not queued while one is still queued or running. If the
  previous catch-up failed the next one is delayed with exponential backoff.
* :class:`CleanupScheduler` - a ``cleanup_old_jobs`` run every ``cleanup_interval_seconds``
  (daily), deleting unprotected jobs and parse results older than
  ``cleanup_max_age_days`` (see :mod:`app.services.cleanup`). Runs once at startup.
* :class:`ScrapeScheduler` - a ``scrape`` run per enabled, importable source every
  ``scrape_sources.scrape_interval_seconds`` (``scrape_interval_seconds`` from the settings
  when the row leaves it empty). Every planned time gets a random delay of up to
  ``scrape_jitter_ratio`` of the interval so the sources do not all fire at once. The plan
  lives in ``scrape_sources.next_scrape_at``, so it survives a scheduler restart; clearing
  it (the API does when the interval changes or a source is re-enabled) makes the scheduler
  re-plan from the source's ``last_run_at``.
"""

from __future__ import annotations

import logging
import os
import random
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job, JobStatus
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import init_db, session_factory
from app.models import ScrapeSource
from app.queue import get_queue
from app.tasks.cleanup import cleanup_old_jobs
from app.tasks.evaluate import evaluate_pending_jobs
from app.tasks.scrape import scrape

log = logging.getLogger(__name__)

SCHEDULER_SLEEP_SECONDS = int(os.getenv("SCHEDULER_SLEEP_SECONDS") or 60)

EVALUATE_JOB_ID = "scheduler-evaluate-pending-jobs"
"""Fixed RQ job id of the catch-up run; only one can exist in the queue at a time."""
EVALUATE_TIMEOUT = 3600
"""RQ ``job_timeout`` for a catch-up run (``evaluate_batch_size`` OpenRouter calls)."""

CLEANUP_JOB_ID = "scheduler-cleanup-old-jobs"
"""Fixed RQ job id of the cleanup run; only one can exist in the queue at a time."""
CLEANUP_TIMEOUT = 600

SCRAPE_JOB_ID_PREFIX = "scheduler-scrape-"
"""Scheduled scrape of source ``key`` runs under the fixed RQ job id ``prefix + key``."""
SCRAPE_TIMEOUT = 600
"""Same ``job_timeout`` as a manual ``POST /api/scrape``."""

ACTIVE_STATUSES = frozenset(
    {JobStatus.QUEUED, JobStatus.STARTED, JobStatus.DEFERRED, JobStatus.SCHEDULED}
)


class EvaluationScheduler:
    """Enqueues ``evaluate_pending_jobs`` every ``interval`` unless one is already active.

    ``tick(now)`` is the only method the loop calls; it returns what it did (``"enqueued"``,
    ``"active"``, ``"waiting"``) so the loop can log it and tests can assert on it.
    """

    def __init__(self, queue: Queue, settings: Settings | None = None) -> None:
        self.queue = queue
        self.settings = settings or get_settings()
        self.interval = timedelta(seconds=self.settings.evaluate_interval_seconds)
        self.max_backoff = timedelta(seconds=self.settings.evaluate_max_backoff_seconds)
        self.next_run_at: datetime = datetime.min.replace(tzinfo=UTC)  # due immediately
        self.consecutive_failures = 0

    def _previous(self) -> Job | None:
        try:
            return Job.fetch(EVALUATE_JOB_ID, connection=self.queue.connection)
        except NoSuchJobError:
            return None

    def _delay_after(self, previous: Job | None) -> timedelta:
        """``interval`` normally; doubled per consecutive failed run, capped."""
        if previous is not None and previous.get_status(refresh=False) == JobStatus.FAILED:
            self.consecutive_failures += 1
        else:
            self.consecutive_failures = 0
        if self.consecutive_failures == 0:
            return self.interval
        return min(self.interval * 2**self.consecutive_failures, self.max_backoff)

    def tick(self, now: datetime | None = None) -> str:
        now = now or datetime.now(UTC)
        if now < self.next_run_at:
            return "waiting"

        previous = self._previous()
        if previous is not None and previous.get_status() in ACTIVE_STATUSES:
            log.info("Catch-up evaluation %s is still %s", previous.id, previous.get_status())
            return "active"

        delay = self._delay_after(previous)
        if previous is not None:
            previous.delete()  # free the id; the previous run's result is in the database
        self.queue.enqueue(
            evaluate_pending_jobs,
            self.settings.evaluate_batch_size,
            job_id=EVALUATE_JOB_ID,
            job_timeout=EVALUATE_TIMEOUT,
            result_ttl=self.settings.job_result_ttl,
            failure_ttl=self.settings.job_result_ttl,
            description="catch-up evaluation of pending jobs",
        )
        self.next_run_at = now + delay
        if self.consecutive_failures:
            log.warning(
                "Previous catch-up evaluation failed (%d in a row); next one in %s",
                self.consecutive_failures,
                delay,
            )
        else:
            log.info("Enqueued catch-up evaluation; next one in %s", delay)
        return "enqueued"


class CleanupScheduler:
    """Enqueues ``cleanup_old_jobs`` every ``cleanup_interval_seconds`` unless one is active.

    ``tick(now)`` returns ``"enqueued"``, ``"active"`` or ``"waiting"``.
    """

    def __init__(self, queue: Queue, settings: Settings | None = None) -> None:
        self.queue = queue
        self.settings = settings or get_settings()
        self.interval = timedelta(seconds=self.settings.cleanup_interval_seconds)
        self.next_run_at: datetime = datetime.min.replace(tzinfo=UTC)  # due immediately

    def tick(self, now: datetime | None = None) -> str:
        now = now or datetime.now(UTC)
        if now < self.next_run_at:
            return "waiting"

        try:
            previous = Job.fetch(CLEANUP_JOB_ID, connection=self.queue.connection)
        except NoSuchJobError:
            previous = None
        if previous is not None:
            if previous.get_status() in ACTIVE_STATUSES:
                return "active"
            previous.delete()

        self.queue.enqueue(
            cleanup_old_jobs,
            self.settings.cleanup_max_age_days,
            job_id=CLEANUP_JOB_ID,
            job_timeout=CLEANUP_TIMEOUT,
            result_ttl=self.settings.job_result_ttl,
            failure_ttl=self.settings.job_result_ttl,
            description=f"cleanup of jobs older than {self.settings.cleanup_max_age_days} days",
        )
        self.next_run_at = now + self.interval
        log.info("Enqueued cleanup; next one in %s", self.interval)
        return "enqueued"


def _aware(value: datetime | None) -> datetime | None:
    """SQLite drops the tzinfo of ``DateTime(timezone=True)``; the stored values are UTC."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class ScrapeScheduler:
    """Enqueues ``scrape(key)`` for every enabled source whose ``next_scrape_at`` has come.

    ``tick(now)`` returns ``{source key: action}`` for the sources it looked at, the action
    being ``"planned"`` (``next_scrape_at`` was empty and got computed), ``"enqueued"``,
    ``"active"`` (its previous scheduled run is still queued/running) or ``"waiting"``.
    Disabled and broken sources are skipped entirely.
    """

    def __init__(
        self,
        queue: Queue,
        settings: Settings | None = None,
        sessions: Callable[[], Session] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.queue = queue
        self.settings = settings or get_settings()
        self.sessions = sessions or session_factory()
        self.rng = rng or random.Random()

    def interval_for(self, row: ScrapeSource) -> timedelta:
        return timedelta(
            seconds=row.scrape_interval_seconds or self.settings.scrape_interval_seconds
        )

    def _jitter(self, interval: timedelta) -> timedelta:
        return interval * self.rng.uniform(0, max(self.settings.scrape_jitter_ratio, 0))

    def _plan(self, row: ScrapeSource, now: datetime) -> datetime:
        """First run time of a source without a plan: one interval after its last run (at
        once if it never ran or that time has passed), plus jitter."""
        last_run = _aware(row.last_run_at)
        base = now if last_run is None else max(now, last_run + self.interval_for(row))
        return base + self._jitter(self.interval_for(row))

    def _active(self, key: str) -> bool:
        try:
            previous = Job.fetch(SCRAPE_JOB_ID_PREFIX + key, connection=self.queue.connection)
        except NoSuchJobError:
            return False
        if previous.get_status() in ACTIVE_STATUSES:
            return True
        previous.delete()  # free the id; the run itself is recorded in scrape_runs
        return False

    def _enqueue(self, key: str) -> None:
        self.queue.enqueue(
            scrape,
            key,
            job_id=SCRAPE_JOB_ID_PREFIX + key,
            job_timeout=SCRAPE_TIMEOUT,
            result_ttl=self.settings.job_result_ttl,
            failure_ttl=self.settings.job_result_ttl,
            meta={"source": key, "scheduled": True},
            description=f"scheduled scrape {key}",
        )

    def tick(self, now: datetime | None = None) -> dict[str, str]:
        # Imported here: app.services.sources and app.tasks.scrape import each other, and
        # the cycle only resolves when app.tasks.scrape is loaded first (it is, above).
        from app.services.sources import runnable_sources, sync_sources

        now = now or datetime.now(UTC)
        actions: dict[str, str] = {}
        with self.sessions() as session:
            sync_sources(session)
            for row in runnable_sources(session):
                next_at = _aware(row.next_scrape_at)
                if next_at is None:
                    row.next_scrape_at = self._plan(row, now)
                    actions[row.key] = "planned"
                    log.info("Planned scrape of %s at %s", row.key, row.next_scrape_at)
                elif now < next_at:
                    actions[row.key] = "waiting"
                elif self._active(row.key):
                    actions[row.key] = "active"
                    log.info("Scheduled scrape of %s is still active", row.key)
                else:
                    self._enqueue(row.key)
                    interval = self.interval_for(row)
                    row.next_scrape_at = now + interval + self._jitter(interval)
                    actions[row.key] = "enqueued"
                    log.info("Enqueued scrape of %s; next at %s", row.key, row.next_scrape_at)
            session.commit()
        return actions


def run_scheduler() -> None:
    init_db()  # the scrape scheduler reads and writes scrape_sources
    queue = get_queue()
    schedulers = [EvaluationScheduler(queue), CleanupScheduler(queue), ScrapeScheduler(queue)]
    while True:
        for scheduled in schedulers:
            try:
                scheduled.tick()
            except Exception:
                log.exception("Scheduler error in %s", type(scheduled).__name__)
        time.sleep(SCHEDULER_SLEEP_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG if get_settings().debug else logging.INFO)
    log.info("Starting scheduler (every %ds)", SCHEDULER_SLEEP_SECONDS)
    run_scheduler()
