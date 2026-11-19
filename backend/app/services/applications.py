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


def sync_interview_plan(session: Session, application: Application) -> None:
    """Make the planned rounds match ``interview_rounds`` (not committed).

    ``interview_rounds`` never drops below the rounds already held (an extra round recorded
    beyond the plan grows it); planned rounds are added blank at the end, or removed from the
    end (blank ones first) when there are too many. ``None``/``0`` clears the plan."""
    plan = application.plan
    if not application.interview_rounds:
        application.interview_rounds = None
        for event in plan:
            application.events.remove(event)
            session.delete(event)
        return
    held = len(held_rounds(application))
    application.interview_rounds = max(application.interview_rounds, held)
    wanted = application.interview_rounds - held
    if len(plan) < wanted:
        ensure_statuses(session)
        status = session.scalar(
            select(ApplicationStatus).where(ApplicationStatus.key == INTERVIEW_STATUS)
        )
        for _ in range(wanted - len(plan)):
            application.events.append(
                ApplicationEvent(status=status, planned=True, occurred_at=None, note="", title="")
            )
    elif len(plan) > wanted:
        blank = [e for e in plan if not (e.title or e.note or e.duration_minutes or e.occurred_at)]
        filled = [e for e in plan if e not in blank]
        # Drop blank rounds from the end first, then filled ones from the end.
        for event in (blank[::-1] + filled[::-1])[: len(plan) - wanted]:
            application.events.remove(event)
            session.delete(event)
