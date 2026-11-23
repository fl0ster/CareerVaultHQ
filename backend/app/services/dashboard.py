"""Queries behind the Dashboard widgets, all aggregated in SQL."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import case, func, not_, select
from sqlalchemy.orm import Session, aliased

from app.models import Application, ApplicationEvent, ApplicationStatus, Company, JobEvaluation, JobParseResult
from app.services.applications import (
    ACCEPTED_STATUS,
    APPLIED_STATUS,
    DECLINED_STATUS,
    INTERVIEW_STATUS,
    OFFER_STATUS,
    REJECTED_STATUS,
)

UPCOMING_LIMIT = 5

# An application "reached" a stage when it went through that state or one only reachable
# after it (an offer implies interviews, a rejection implies having applied, ...).
REACHED = {
    APPLIED_STATUS: {APPLIED_STATUS, INTERVIEW_STATUS, OFFER_STATUS, ACCEPTED_STATUS, DECLINED_STATUS, REJECTED_STATUS},
    INTERVIEW_STATUS: {INTERVIEW_STATUS, OFFER_STATUS, ACCEPTED_STATUS, DECLINED_STATUS},
    OFFER_STATUS: {OFFER_STATUS, ACCEPTED_STATUS, DECLINED_STATUS},
    ACCEPTED_STATUS: {ACCEPTED_STATUS},
}
RESPONDED = "RESPONDED"
"""Pseudo-stage: the employer answered an application (any reached state past APPLIED)."""
_STAGES = {**REACHED, RESPONDED: REACHED[APPLIED_STATUS] - {APPLIED_STATUS}}


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def scored_counts(session: Session, threshold: float) -> tuple[int, int]:
    """(scored jobs, relevant jobs) by each job's newest evaluation; a job with an
    application counts as relevant even if a later re-score dropped it."""
    newer = aliased(JobEvaluation)
    latest = (
        select(JobEvaluation.job_parse_result_id, JobEvaluation.match_probability)
        .where(
            not_(
                select(newer.id)
                .where(newer.job_parse_result_id == JobEvaluation.job_parse_result_id, newer.id > JobEvaluation.id)
                .exists()
            )
        )
        .subquery()
    )
    applied = select(Application.id).where(Application.job_parse_result_id == latest.c.job_parse_result_id).exists()
    relevant = func.sum(case(((latest.c.match_probability >= threshold) | applied, 1), else_=0))
    scored, rel = session.execute(select(func.count(), relevant).select_from(latest)).one()
    return scored or 0, rel or 0


def _held_per_application():
    """One row per application: a 0/1 flag per stage reached, and when it first reached APPLIED."""
    held = (
        select(ApplicationEvent.application_id, ApplicationStatus.key, ApplicationEvent.occurred_at)
        .join(ApplicationStatus, ApplicationStatus.id == ApplicationEvent.status_id)
        .where(ApplicationEvent.planned.is_(False))
        .subquery()
    )
    flags = [func.max(case((held.c.key.in_(keys), 1), else_=0)).label(stage) for stage, keys in _STAGES.items()]
    applied_on = func.min(case((held.c.key == APPLIED_STATUS, held.c.occurred_at))).label("applied_on")
    return (
        select(Application.id.label("application_id"), *flags, applied_on)
        .outerjoin(held, held.c.application_id == Application.id)
        .group_by(Application.id)
        .subquery()
    )


def reached_counts(session: Session) -> tuple[int, dict[str, int]]:
    """(applications, ``{stage: applications that reached it}``), stages including ``RESPONDED``."""
    per_app = _held_per_application()
    row = session.execute(select(func.count(), *(func.coalesce(func.sum(per_app.c[stage]), 0) for stage in _STAGES))).one()
    return row[0], dict(zip(_STAGES, row[1:], strict=True))


def applied_per_day(session: Session, since: date) -> dict[date, int]:
    """``{day: applications that first reached APPLIED that day}`` from ``since`` on."""
    per_app = _held_per_application()
    day = func.date(per_app.c.applied_on)
    rows = session.execute(
        select(day, func.count())
        .where(per_app.c.applied_on >= datetime.combine(since, datetime.min.time(), UTC))
        .group_by(day)
    ).all()
    # SQLite returns the day as text, PostgreSQL as a date.
    return {d if isinstance(d, date) else date.fromisoformat(d): n for d, n in rows}


@dataclass
class Upcoming:
    application_id: int
    job_title: str | None
    company: str | None
    title: str
    round: int
    scheduled_at: datetime


def upcoming_rounds(session: Session, now: datetime) -> list[Upcoming]:
    """The next scheduled (planned, dated, not past) interview rounds, soonest first."""
    planned = session.execute(
        select(ApplicationEvent, JobParseResult.title, Company.name)
        .join(Application, Application.id == ApplicationEvent.application_id)
        .join(JobParseResult, JobParseResult.id == Application.job_parse_result_id)
        .outerjoin(Company, Company.id == JobParseResult.company_id)
        .where(ApplicationEvent.planned.is_(True), ApplicationEvent.occurred_at >= now)
        .order_by(ApplicationEvent.occurred_at, ApplicationEvent.id)
        .limit(UPCOMING_LIMIT)
    ).all()
    if not planned:
        return []
    # Round number = held interviews + position among the planned rounds (by id).
    app_ids = {event.application_id for event, _, _ in planned}
    held = dict(
        session.execute(
            select(ApplicationEvent.application_id, func.count())
            .join(ApplicationStatus, ApplicationStatus.id == ApplicationEvent.status_id)
            .where(
                ApplicationEvent.application_id.in_(app_ids),
                ApplicationEvent.planned.is_(False),
                ApplicationStatus.key == INTERVIEW_STATUS,
            )
            .group_by(ApplicationEvent.application_id)
        ).all()
    )
    plan_ids: dict[int, list[int]] = {}
    for app_id, event_id in session.execute(
        select(ApplicationEvent.application_id, ApplicationEvent.id)
        .where(ApplicationEvent.application_id.in_(app_ids), ApplicationEvent.planned.is_(True))
        .order_by(ApplicationEvent.id)
    ):
        plan_ids.setdefault(app_id, []).append(event_id)
    return [
        Upcoming(
            application_id=event.application_id,
            job_title=title,
            company=company,
            title=event.title or "",
            round=held.get(event.application_id, 0) + plan_ids[event.application_id].index(event.id) + 1,
            scheduled_at=as_utc(event.occurred_at),
        )
        for event, title, company in planned
    ]
