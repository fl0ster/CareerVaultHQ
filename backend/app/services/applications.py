"""Helpers shared by the applications API."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Application, ApplicationEvent, ApplicationStatus, JobDecision


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


INTERVIEW_STATUS = "INTERVIEW"
"""State of interview rounds; planned rounds always have it."""


def held_rounds(application: Application) -> list[ApplicationEvent]:
    """Interview rounds that already took place."""
    return [e for e in application.history if e.status.key == INTERVIEW_STATUS]


def set_interview_rounds(
    session: Session, application: Application, rounds: int, interview: ApplicationStatus
) -> None:
    """Add blank planned rounds at the end, or drop them from the end, so the application has
    ``rounds`` interview rounds (held + planned; at least the held ones). Not committed."""
    plan = application.plan
    wanted = max(rounds - len(held_rounds(application)), 0)
    for event in plan[wanted:]:
        application.events.remove(event)
        session.delete(event)
    for _ in range(wanted - len(plan)):
        application.events.append(
            ApplicationEvent(status=interview, planned=True, occurred_at=None)
        )
