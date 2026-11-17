"""``cleanup_old_jobs``: RQ task the scheduler enqueues daily (see ``app.scheduler``)."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from app.db import init_db, session_factory
from app.services.cleanup import cleanup_old_jobs as _cleanup
from app.services.timeline import prune_read_events

TIMELINE_MAX_AGE_DAYS = 90


def cleanup_old_jobs(max_age_days: int) -> dict[str, Any]:
    """Delete unprotected jobs / parse results older than ``max_age_days`` days, and read
    timeline events older than ``TIMELINE_MAX_AGE_DAYS`` (or ``max_age_days`` if longer)."""
    init_db()
    older_than = datetime.now(UTC) - timedelta(days=max_age_days)
    with session_factory()() as session:
        summary = asdict(_cleanup(session, older_than))
        summary["timeline_events_deleted"] = prune_read_events(
            session, datetime.now(UTC) - timedelta(days=max(max_age_days, TIMELINE_MAX_AGE_DAYS))
        )
    summary["older_than"] = summary["older_than"].isoformat()
    return summary
