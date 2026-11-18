"""Helpers shared by the applications API."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApplicationStatus, JobDecision


def set_job_decision(session: Session, job_parse_result_id: int, decision: str) -> JobDecision:
    """Record (or overwrite) the user's decision about a parsed job. Not committed."""
    row = session.scalar(
        select(JobDecision).where(JobDecision.job_parse_result_id == job_parse_result_id)
    )
    if row is None:
        row = JobDecision(job_parse_result_id=job_parse_result_id, decision=decision)
        session.add(row)
    else:
        row.decision = decision
    return row


def ensure_statuses(session: Session) -> None:
    """Create the default ``ApplicationStatus`` rows that do not exist yet (idempotent;
    existing rows, including edited labels and custom statuses, are left alone)."""
    existing = set(session.scalars(select(ApplicationStatus.key)))
    missing = [
        ApplicationStatus(key=key, label=label, position=i * 10, next_key=next_key or None)
        for i, (key, label, next_key) in enumerate(ApplicationStatus.DEFAULTS)
        if key not in existing
    ]
    if missing:
        session.add_all(missing)
        session.commit()
