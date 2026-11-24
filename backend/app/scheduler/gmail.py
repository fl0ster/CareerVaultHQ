"""``check_rejection_mails`` every ``gmail_monitor_settings.interval_seconds`` while the
Gmail rejection monitor is enabled and configured.

The plan lives in ``gmail_monitor_settings.next_run_at`` (cleared by the API when the
interval changes or the monitor is re-enabled, which makes the next tick run at once). A
manual run (``POST /api/gmail-monitor/run``) uses the same fixed RQ job id, so a scheduled
and a manual check never overlap.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from rq import Queue
from rq.job import Job
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import session_factory
from app.scheduler.common import aware, fetch_job, free_job_id, is_active
from app.services.gmail_monitor import get_monitor_settings, is_configured
from app.tasks.gmail import check_rejection_mails

log = logging.getLogger(__name__)

GMAIL_JOB_ID = "scheduler-gmail-rejections"
GMAIL_TIMEOUT = 900
MIN_INTERVAL_SECONDS = 60


def enqueue_gmail_check(queue: Queue, settings: Settings, *, scheduled: bool) -> Job:
    """Enqueue ``check_rejection_mails`` under the fixed id, or return the job already
    queued/running under it."""
    previous = fetch_job(queue, GMAIL_JOB_ID)
    if is_active(previous):
        return previous  # type: ignore[return-value]
    free_job_id(previous)
    return queue.enqueue(
        check_rejection_mails,
        job_id=GMAIL_JOB_ID,
        job_timeout=GMAIL_TIMEOUT,
        result_ttl=settings.job_result_ttl,
        failure_ttl=settings.job_result_ttl,
        meta={"scheduled": scheduled},
        description="check Gmail for rejection mails",
    )


class GmailMonitorScheduler:
    """``tick(now)`` returns ``"disabled"`` (off or not configured), ``"waiting"``,
    ``"active"`` (the previous check is still queued/running) or ``"enqueued"``."""

    def __init__(
        self,
        queue: Queue,
        settings: Settings | None = None,
        sessions: Callable[[], Session] | None = None,
    ) -> None:
        self.queue = queue
        self.settings = settings or get_settings()
        self.sessions = sessions or session_factory()

    def tick(self, now: datetime | None = None) -> str:
        now = now or datetime.now(UTC)
        with self.sessions() as session:
            row = get_monitor_settings(session)
            if not row.enabled or not is_configured(session, row):
                return "disabled"
            next_at = aware(row.next_run_at)
            if next_at is not None and now < next_at:
                return "waiting"
            if is_active(fetch_job(self.queue, GMAIL_JOB_ID)):
                return "active"
            enqueue_gmail_check(self.queue, self.settings, scheduled=True)
            interval = max(row.interval_seconds or 0, MIN_INTERVAL_SECONDS)
            row.next_run_at = now + timedelta(seconds=interval)
            session.commit()
            log.info("Enqueued Gmail rejection check; next at %s", row.next_run_at)
            return "enqueued"
