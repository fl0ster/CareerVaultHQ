"""Numbers behind the Dashboard, all counted in SQL.

Each query returns either one row of aggregates or a bounded handful of rows; no
application, event or job is loaded into Python to be counted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import ColumnElement, and_, case, func, not_, or_, select
from sqlalchemy.orm import Session, aliased

from app.models import Application, ApplicationEvent, ApplicationStatus, Company, JobEvaluation, JobParseResult
from app.schemas.dashboard import DashboardStats, Flow, FlowKind, FlowLink, FlowNode, UpcomingRound, WeekCount
from app.services.applications import (
    ACCEPTED_STATUS,
    APPLIED_STATUS,
    CLOSED_STATUS,
    DECLINED_STATUS,
    FINAL_STATUSES,
    INTERVIEW_STATUS,
    OFFER_STATUS,
    REJECTED_STATUS,
    application_count,
    current_stage_counts,
)

WEEKS = 8
"""Weeks shown by the weekly activity widget, the current one included."""
UPCOMING_LIMIT = 5

# An application "reached" a stage when it went through that state or one only reachable
# after it (an offer implies interviews, a rejection implies having applied, ...).
REACHED_APPLIED = (APPLIED_STATUS, INTERVIEW_STATUS, OFFER_STATUS, ACCEPTED_STATUS, DECLINED_STATUS, REJECTED_STATUS)
REACHED_INTERVIEW = (INTERVIEW_STATUS, OFFER_STATUS, ACCEPTED_STATUS, DECLINED_STATUS)
REACHED_OFFER = (OFFER_STATUS, ACCEPTED_STATUS, DECLINED_STATUS)


@dataclass(frozen=True)
class Outcomes:
    """How many applications reached each stage and where the others stopped."""

    total: int
    applied: int
    responded: int
    """Applied and heard back: interviewed (or further) or rejected."""
    not_applied_closed: int
    interviewed: int
    applied_rejected: int
    """Rejected without an interview."""
    applied_closed: int
    offered: int
    interview_rejected: int
    """Rejected after interviewing, without an offer."""
    interview_closed: int
    accepted: int
    declined: int


def _held_state_flags():
    """One row per application with held events: 0/1 flags for the states it went through."""

    def went_through(*keys: str):
        return func.max(case((ApplicationStatus.key.in_(keys), 1), else_=0))

    return (
        select(
            went_through(*REACHED_APPLIED).label("applied"),
            went_through(*REACHED_INTERVIEW).label("interview"),
            went_through(*REACHED_OFFER).label("offer"),
            went_through(ACCEPTED_STATUS).label("accepted"),
            went_through(DECLINED_STATUS).label("declined"),
            went_through(REJECTED_STATUS).label("rejected"),
            went_through(CLOSED_STATUS).label("closed"),
        )
        .select_from(ApplicationEvent)
        .join(ApplicationStatus, ApplicationStatus.id == ApplicationEvent.status_id)
        .where(ApplicationEvent.planned.is_(False))
        .group_by(ApplicationEvent.application_id)
        .subquery()
    )


def _count_where(*conditions: ColumnElement[bool]) -> ColumnElement[int]:
    return func.coalesce(func.sum(case((and_(*conditions), 1), else_=0)), 0)


def application_outcomes(session: Session) -> Outcomes:
    f = _held_state_flags().c
    row = session.execute(
        select(
            _count_where(f.applied == 1),
            _count_where(f.applied == 1, or_(f.interview == 1, f.rejected == 1)),
            _count_where(f.applied == 0, f.closed == 1),
            _count_where(f.interview == 1),
            _count_where(f.applied == 1, f.interview == 0, f.rejected == 1),
            _count_where(f.applied == 1, f.interview == 0, f.rejected == 0, f.closed == 1),
            _count_where(f.offer == 1),
            _count_where(f.interview == 1, f.offer == 0, f.rejected == 1),
            _count_where(f.interview == 1, f.offer == 0, f.rejected == 0, f.closed == 1),
            _count_where(f.accepted == 1),
            _count_where(f.offer == 1, f.accepted == 0, f.declined == 1),
        )
    ).one()
    return Outcomes(application_count(session), *row)


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
    has_application = select(Application.id).where(Application.job_parse_result_id == latest.c.job_parse_result_id).exists()
    scored, relevant = session.execute(
        select(func.count(), _count_where(or_(latest.c.match_probability >= threshold, has_application)))
    ).one()
    return scored, relevant


def weekly_applied(session: Session, now: datetime, weeks: int = WEEKS) -> list[WeekCount]:
    """Applications per week of first reaching ``APPLIED``, the last ``weeks`` weeks (UTC,
    Monday-based), oldest first. One aggregate row, one column per week."""
    this_week = now.astimezone(UTC).date() - timedelta(days=now.astimezone(UTC).weekday())
    starts = [this_week - timedelta(weeks=i) for i in range(weeks - 1, -1, -1)]
    bounds = [datetime.combine(day, time(), tzinfo=UTC) for day in [*starts, starts[-1] + timedelta(weeks=1)]]

    first_applied = (
        select(func.min(ApplicationEvent.occurred_at).label("at"))
        .select_from(ApplicationEvent)
        .join(ApplicationStatus, ApplicationStatus.id == ApplicationEvent.status_id)
        .where(ApplicationEvent.planned.is_(False), ApplicationStatus.key == APPLIED_STATUS)
        .group_by(ApplicationEvent.application_id)
        .subquery()
    )
    at = first_applied.c.at
    counts = session.execute(
        select(*(_count_where(at >= start, at < end) for start, end in zip(bounds, bounds[1:], strict=False)))
    ).one()
    return [WeekCount(week_start=day, count=count) for day, count in zip(starts, counts, strict=True)]


def upcoming_rounds(session: Session, now: datetime, limit: int = UPCOMING_LIMIT) -> list[UpcomingRound]:
    """The next scheduled (planned, dated, not past) interview rounds, soonest first. The
    round number is the held interviews plus the round's place among the planned ones."""
    held = aliased(ApplicationEvent)
    planned_before = aliased(ApplicationEvent)
    held_interviews = (
        select(func.count())
        .select_from(held)
        .join(ApplicationStatus, ApplicationStatus.id == held.status_id)
        .where(
            held.application_id == ApplicationEvent.application_id,
            held.planned.is_(False),
            ApplicationStatus.key == INTERVIEW_STATUS,
        )
        .scalar_subquery()
    )
    place_in_plan = (
        select(func.count())
        .select_from(planned_before)
        .where(
            planned_before.application_id == ApplicationEvent.application_id,
            planned_before.planned.is_(True),
            planned_before.id <= ApplicationEvent.id,
        )
        .scalar_subquery()
    )
    rows = session.execute(
        select(
            ApplicationEvent.application_id,
            ApplicationEvent.title,
            ApplicationEvent.occurred_at,
            (held_interviews + place_in_plan).label("round"),
            JobParseResult.title,
            Company.name,
        )
        .join(Application, Application.id == ApplicationEvent.application_id)
        .join(JobParseResult, JobParseResult.id == Application.job_parse_result_id)
        .outerjoin(Company, Company.id == JobParseResult.company_id)
        .where(ApplicationEvent.planned.is_(True), ApplicationEvent.occurred_at >= now)
        .order_by(ApplicationEvent.occurred_at, ApplicationEvent.id)
        .limit(limit)
    ).all()
    return [
        UpcomingRound(
            application_id=app_id,
            job_title=job_title,
            company=company,
            title=title or "",
            round=round_number,
            scheduled_at=_as_utc(scheduled_at),
        )
        for app_id, title, scheduled_at, round_number, job_title, company in rows
    ]


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def build_flow(scored: int, relevant: int, inbox: int, o: Outcomes) -> Flow:
    """The Sankey graph from scored jobs to answered offers. Job counts are made consistent
    with the application counts (each node passes on at most what reaches it), e.g. for an
    application whose job lost its evaluation."""
    relevant = max(relevant, o.total + inbox)
    scored = max(scored, relevant)
    # (column of the source, source, target, target label, target kind, count)
    steps: list[tuple[int, str, str, str, FlowKind, int]] = [
        (0, "scored", "relevant", "Relevant", "stage", relevant),
        (0, "scored", "scored:drop", "Not relevant", "drop", scored - relevant),
        (1, "relevant", "shortlisted", "Shortlisted", "stage", o.total),
        (1, "relevant", "relevant:waiting", "To review", "pending", inbox),
        (1, "relevant", "relevant:drop", "Passed on", "drop", relevant - o.total - inbox),
        (2, "shortlisted", "applied", "Applied", "stage", o.applied),
        (2, "shortlisted", "shortlisted:waiting", "Not applied yet", "pending", o.total - o.applied - o.not_applied_closed),
        (2, "shortlisted", "shortlisted:closed", "Closed", "drop", o.not_applied_closed),
        (3, "applied", "interview", "Interviewed", "stage", o.interviewed),
        (
            3,
            "applied",
            "applied:waiting",
            "Awaiting reply",
            "pending",
            o.applied - o.interviewed - o.applied_rejected - o.applied_closed,
        ),
        (3, "applied", "applied:rejected", "Rejected", "rejected", o.applied_rejected),
        (3, "applied", "applied:closed", "Closed", "drop", o.applied_closed),
        (4, "interview", "offer", "Offer", "stage", o.offered),
        (
            4,
            "interview",
            "interview:waiting",
            "In process",
            "pending",
            o.interviewed - o.offered - o.interview_rejected - o.interview_closed,
        ),
        (4, "interview", "interview:rejected", "Rejected", "rejected", o.interview_rejected),
        (4, "interview", "interview:closed", "Closed", "drop", o.interview_closed),
        (5, "offer", "offer:accepted", "Accepted", "accepted", o.accepted),
        (5, "offer", "offer:waiting", "Deciding", "pending", o.offered - o.accepted - o.declined),
        (5, "offer", "offer:declined", "Declined", "drop", o.declined),
    ]
    nodes: dict[str, FlowNode] = {}
    links: list[FlowLink] = []
    for column, source, target, label, kind, value in steps:
        if value <= 0:
            continue
        nodes.setdefault(source, FlowNode(id=source, label="Jobs scored", column=0, kind="stage"))
        nodes[target] = FlowNode(id=target, label=label, column=column + 1, kind=kind)
        links.append(FlowLink(source=source, target=target, value=value))
    order: dict[FlowKind, int] = {"stage": 0, "accepted": 1, "pending": 2, "rejected": 3, "drop": 4}
    return Flow(nodes=sorted(nodes.values(), key=lambda n: (n.column, order[n.kind])), links=links)


def dashboard_stats(session: Session, *, threshold: float, jobs_inbox: int, now: datetime) -> DashboardStats:
    scored, relevant = scored_counts(session, threshold)
    outcomes = application_outcomes(session)
    stages = current_stage_counts(session)
    return DashboardStats(
        flow=build_flow(scored, relevant, jobs_inbox, outcomes),
        jobs_inbox=jobs_inbox,
        active=outcomes.total - sum(stages.get(key, 0) for key in FINAL_STATUSES),
        interviews=stages.get(INTERVIEW_STATUS, 0),
        offers=stages.get(OFFER_STATUS, 0),
        responded=outcomes.responded,
        applied=outcomes.applied,
        weekly_applied=weekly_applied(session, now),
        upcoming=upcoming_rounds(session, now),
    )
