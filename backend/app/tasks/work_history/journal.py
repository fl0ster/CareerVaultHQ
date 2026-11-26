"""Regenerating a position's work journal (``app.services.work_journal``) as a background (RQ)
job.

Regeneration makes several OpenRouter calls per stale month (generation plus the
truthfulness check, each retried once) and more for the role description, so it never runs
in an API request: ``POST /api/work-history/{id}/journal/refresh`` queues
``refresh_work_journal(role_id)`` and the UI polls ``GET .../journal`` until it is done.

Each role has one fixed RQ job id, so asking again while a refresh is queued or running
returns that job instead of stacking another. The warnings of the last run are kept on the
role (``journal_warnings``) because RQ results expire.
"""

from __future__ import annotations

import logging
from typing import Any

from rq import Queue
from rq.job import Job

from app.config import Settings, get_settings
from app.db import init_db, session_factory
from app.models import WorkHistoryEntry
from app.scheduler.common import fetch_job, free_job_id, is_active
from app.services.openrouter import OpenRouterNotConfigured, OpenRouterService
from app.services.work_journal import refresh_journal

log = logging.getLogger(__name__)

REFRESH_TIMEOUT = 1800
"""RQ ``job_timeout`` (seconds): a long backfill can take dozens of sequential calls on a Pi."""
NOT_CONFIGURED = "The journal could not be summarised: OPENROUTER_API_KEY is not set."


def refresh_job_id(role_id: int) -> str:
    """The fixed RQ job id of a role's journal refresh."""
    return f"work-journal-refresh-{role_id}"


def is_refreshing(queue: Queue, role_id: int) -> bool:
    """A refresh of the role's journal is queued or running."""
    return is_active(fetch_job(queue, refresh_job_id(role_id)))


def refresh_work_journal(role_id: int) -> dict[str, Any]:
    """RQ entry point: :func:`refresh_journal` the position ``role_id`` and keep its warnings."""
    init_db()
    with session_factory()() as session:
        role = session.get(WorkHistoryEntry, role_id)
        if role is None or role.kind != WorkHistoryEntry.KIND_JOB:
            log.info("Work-history entry %d is gone or not a position; no journal to refresh", role_id)
            return {"role_id": role_id, "warnings": []}
        try:
            warnings = refresh_journal(session, role, OpenRouterService(session))
        except OpenRouterNotConfigured:
            session.rollback()
            warnings = [NOT_CONFIGURED]
        role = session.get(WorkHistoryEntry, role_id)
        if role is not None:
            role.journal_warnings = warnings or None
            session.commit()
        return {"role_id": role_id, "warnings": warnings}


def enqueue_journal_refresh(queue: Queue, role_id: int, settings: Settings | None = None) -> Job:
    """Queue :func:`refresh_work_journal` for the role under its fixed id, or return the job
    already queued or running under it. Raises when the queue is unreachable."""
    settings = settings or get_settings()
    previous = fetch_job(queue, refresh_job_id(role_id))
    if is_active(previous):
        return previous  # type: ignore[return-value]
    free_job_id(previous)
    return queue.enqueue(
        refresh_work_journal,
        role_id,
        job_id=refresh_job_id(role_id),
        job_timeout=REFRESH_TIMEOUT,
        result_ttl=settings.job_result_ttl,
        failure_ttl=settings.job_result_ttl,
        meta={"work_history_id": role_id},
        description=f"refresh the work journal of work history {role_id}",
    )
