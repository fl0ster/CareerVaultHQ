"""``scrape`` run per enabled, importable source every ``scrape_sources.scrape_interval_seconds``
(``scrape_interval_seconds`` from the settings when the row leaves it empty).

Every planned time gets a random delay of up to ``scrape_jitter_ratio`` of the interval so
the sources do not all fire at once. The plan lives in ``scrape_sources.next_scrape_at``, so
it survives a scheduler restart; clearing it (the API does when the interval changes or a
source is re-enabled) makes the scheduler re-plan from the source's ``last_run_at``.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from rq import Queue
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import session_factory
from app.models import ScrapeSource
from app.scheduler.common import aware, fetch_job, free_job_id, is_active
from app.tasks.scrape import scrape

log = logging.getLogger(__name__)

SCRAPE_JOB_ID_PREFIX = "scheduler-scrape-"
"""Scheduled scrape of source ``key`` runs under the fixed RQ job id ``prefix + key``."""
SCRAPE_TIMEOUT = 600
"""Same ``job_timeout`` as a manual ``POST /api/scrape``."""


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

    def tick(self, now: datetime | None = None) -> dict[str, str]:
        # Imported here: app.services.sources and app.tasks.scrape import each other, and
        # the cycle only resolves when app.tasks.scrape is loaded first (it is, above).
        from app.services.sources import runnable_sources, sync_sources

        now = now or datetime.now(UTC)
        with self.sessions() as session:
            sync_sources(session)
            actions = {row.key: self._tick_source(row, now) for row in runnable_sources(session)}
            session.commit()
        return actions

    def _tick_source(self, row: ScrapeSource, now: datetime) -> str:
        next_at = aware(row.next_scrape_at)
        if next_at is None:
            row.next_scrape_at = self._plan(row, now)
            log.info("Planned scrape of %s at %s", row.key, row.next_scrape_at)
            return "planned"
        if now < next_at:
            return "waiting"
        if self._active(row.key):
            log.info("Scheduled scrape of %s is still active", row.key)
            return "active"
        self._enqueue(row.key)
        interval = self.interval_for(row)
        row.next_scrape_at = now + interval + self._jitter(interval)
        log.info("Enqueued scrape of %s; next at %s", row.key, row.next_scrape_at)
        return "enqueued"

    def interval_for(self, row: ScrapeSource) -> timedelta:
        return timedelta(
            seconds=row.scrape_interval_seconds or self.settings.scrape_interval_seconds
        )

    def _jitter(self, interval: timedelta) -> timedelta:
        """A random share of ``interval``, up to ``scrape_jitter_ratio``."""
        return interval * self.rng.uniform(0, max(self.settings.scrape_jitter_ratio, 0))

    def _plan(self, row: ScrapeSource, now: datetime) -> datetime:
        """First run time of a source without a plan: one interval after its last run (at
        once if it never ran or that time has passed), plus jitter."""
        interval = self.interval_for(row)
        last_run = aware(row.last_run_at)
        base = now if last_run is None else max(now, last_run + interval)
        return base + self._jitter(interval)

    def _active(self, key: str) -> bool:
        previous = fetch_job(self.queue, SCRAPE_JOB_ID_PREFIX + key)
        if is_active(previous):
            return True
        free_job_id(previous)
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
