"""Numbers behind the Dashboard widgets.

``GET /api/dashboard/stats`` returns, in one request, the job-search funnel (scored jobs
down to accepted offers), a few headline counts, applications sent per week and the next
scheduled interview rounds.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, not_, select
from sqlalchemy.orm import Session, aliased

from app.api.routes.jobs import inbox_count
from app.config import Settings, get_settings
from app.db import get_session
from app.models import Application, ApplicationEvent, ApplicationStatus, Company, JobEvaluation, JobParseResult
from app.services.applications import (
    ACCEPTED_STATUS,
    APPLIED_STATUS,
    CLOSED_STATUS,
    DECLINED_STATUS,
    FINAL_STATUSES,
    INTERVIEW_STATUS,
    OFFER_STATUS,
    REJECTED_STATUS,
    current_stage_counts,
)

router = APIRouter()

WEEKS = 8
"""Weeks shown by the weekly activity widget, the current one included."""
UPCOMING_LIMIT = 5

# An application "reached" a stage when it went through that state or one only reachable
# after it (an offer implies interviews, a rejection implies having applied, ...).
_REACHED = {
    APPLIED_STATUS: {APPLIED_STATUS, INTERVIEW_STATUS, OFFER_STATUS, ACCEPTED_STATUS, DECLINED_STATUS, REJECTED_STATUS},
    INTERVIEW_STATUS: {INTERVIEW_STATUS, OFFER_STATUS, ACCEPTED_STATUS, DECLINED_STATUS},
    OFFER_STATUS: {OFFER_STATUS, ACCEPTED_STATUS, DECLINED_STATUS},
    ACCEPTED_STATUS: {ACCEPTED_STATUS},
}
_RESPONDED = _REACHED[APPLIED_STATUS] - {APPLIED_STATUS}
"""States that mean the employer answered an application."""


FlowKind = Literal["stage", "drop", "rejected", "pending", "accepted"]


class FlowNode(BaseModel):
    id: str
    label: str
    column: int
    """0 = scored jobs; each stage of the search one column further right."""
    kind: FlowKind
    """``stage``: the search continues from it; the others are where flows end — ``drop``
    (filtered out, passed on, closed), ``rejected``, ``pending`` (still waiting) or
    ``accepted``."""


class FlowLink(BaseModel):
    source: str
    target: str
    value: int


class Flow(BaseModel):
    """Sankey graph of the search: every scored job flows from left to right until it stops.
    Nodes and links without anything flowing through them are left out."""

    nodes: list[FlowNode]
    links: list[FlowLink]


class WeekCount(BaseModel):
    week_start: date
    """Monday of the week (UTC)."""
    count: int


class UpcomingRound(BaseModel):
    application_id: int
    job_title: str | None
    company: str | None
    title: str
    """Kind of round ("Technical", ...); empty when not named."""
    round: int
    """1-based round number."""
    scheduled_at: datetime


class DashboardStats(BaseModel):
    flow: Flow
    jobs_inbox: int
    active: int
    """Applications whose current state is not final."""
    interviews: int
    """Applications currently in the interview stage."""
    offers: int
    """Applications currently holding an offer."""
    responded: int
    """Applied applications that heard back (interview, rejection or offer)."""
    applied: int
    weekly_applied: list[WeekCount]
    """Applications sent (``APPLIED`` reached) per week, oldest first."""
    upcoming: list[UpcomingRound]
    """Scheduled interview rounds from now on, soonest first."""


def _scored_counts(session: Session, threshold: float) -> tuple[int, int]:
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
    scored = session.scalar(select(func.count()).select_from(latest)) or 0
    relevant = (
        session.scalar(select(func.count()).select_from(latest).where((latest.c.match_probability >= threshold) | applied))
        or 0
    )
    return scored, relevant


# Columns of the flow and the nodes the search continues through.
_STAGES = [
    ("scored", "Jobs scored"),
    ("relevant", "Relevant"),
    ("shortlisted", "Shortlisted"),
    ("applied", "Applied"),
    ("interview", "Interviewed"),
    ("offer", "Offer"),
]


def _application_step(keys: set[str], stage: str) -> tuple[str, str, FlowKind] | None:
    """Where an application at ``stage`` (it went through the states ``keys``) goes next:
    ``None`` when it moved on to the next stage, else ``(id suffix, label, kind)`` of the
    node it stopped at."""
    if stage == "shortlisted":
        if keys & _REACHED[APPLIED_STATUS]:
            return None
        return ("closed", "Closed", "drop") if CLOSED_STATUS in keys else ("waiting", "Not applied yet", "pending")
    if stage == "offer":
        if ACCEPTED_STATUS in keys:
            return ("accepted", "Accepted", "accepted")
        if DECLINED_STATUS in keys:
            return ("declined", "Declined", "drop")
        return ("waiting", "Deciding", "pending")
    following = INTERVIEW_STATUS if stage == "applied" else OFFER_STATUS
    if keys & _REACHED[following]:
        return None
    if REJECTED_STATUS in keys:
        return ("rejected", "Rejected", "rejected")
    if CLOSED_STATUS in keys:
        return ("closed", "Closed", "drop")
    return ("waiting", "Awaiting reply" if stage == "applied" else "In process", "pending")


def _flow(scored: int, relevant: int, inbox: int, applications: list[set[str]]) -> Flow:
    """The Sankey graph from scored jobs to accepted offers. Counts are made consistent
    (each node passes on at most what reaches it) should the job and application counts
    disagree, e.g. an application whose job lost its evaluation."""
    shortlisted = len(applications)
    relevant = max(relevant, shortlisted + inbox)
    scored = max(scored, relevant)
    nodes: dict[str, FlowNode] = {}
    links: list[FlowLink] = []

    def link(column: int, source: str, target: str, label: str, kind: FlowKind, value: int) -> None:
        if value <= 0:
            return
        if not nodes:
            nodes[source] = FlowNode(id=source, label=_STAGES[0][1], column=0, kind="stage")
        nodes.setdefault(target, FlowNode(id=target, label=label, column=column + 1, kind=kind))
        links.append(FlowLink(source=source, target=target, value=value))

    link(0, "scored", "relevant", "Relevant", "stage", relevant)
    link(0, "scored", "scored:drop", "Not relevant", "drop", scored - relevant)
    link(1, "relevant", "shortlisted", "Shortlisted", "stage", shortlisted)
    link(1, "relevant", "relevant:waiting", "To review", "pending", inbox)
    link(1, "relevant", "relevant:drop", "Passed on", "drop", relevant - shortlisted - inbox)

    at_stage = applications
    for column, (stage, _) in enumerate(_STAGES[2:], start=2):
        moved_on: list[set[str]] = []
        stopped: dict[tuple[str, str, FlowKind], int] = {}
        for keys in at_stage:
            step = _application_step(keys, stage)
            if step is None:
                moved_on.append(keys)
            else:
                stopped[step] = stopped.get(step, 0) + 1
        if column + 1 < len(_STAGES):
            following, label = _STAGES[column + 1]
            link(column, stage, following, label, "stage", len(moved_on))
        for (suffix, label, kind), count in stopped.items():
            link(column, stage, f"{stage}:{suffix}", label, kind, count)
        at_stage = moved_on

    order = {"stage": 0, "accepted": 1, "pending": 2, "rejected": 3, "drop": 4}
    return Flow(
        nodes=sorted(nodes.values(), key=lambda n: (n.column, order[n.kind])),
        links=links,
    )


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@router.get("/stats", response_model=DashboardStats)
def dashboard_stats(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DashboardStats:
    now = datetime.now(UTC)
    scored, relevant = _scored_counts(session, settings.relevant_job_threshold)

    # Held states of every application, and when each first reached APPLIED.
    reached: dict[int, set[str]] = {app_id: set() for app_id in session.scalars(select(Application.id))}
    applied_on: dict[int, datetime] = {}
    rows = session.execute(
        select(ApplicationEvent.application_id, ApplicationStatus.key, ApplicationEvent.occurred_at)
        .join(ApplicationStatus, ApplicationStatus.id == ApplicationEvent.status_id)
        .where(ApplicationEvent.planned.is_(False))
    ).all()
    for app_id, key, occurred_at in rows:
        reached.setdefault(app_id, set()).add(key)
        if key == APPLIED_STATUS and occurred_at is not None:
            when = _as_utc(occurred_at)
            if app_id not in applied_on or when < applied_on[app_id]:
                applied_on[app_id] = when

    def count_reaching(stage: str) -> int:
        return sum(1 for keys in reached.values() if keys & _REACHED[stage])

    jobs_inbox = inbox_count(session, settings.relevant_job_threshold)

    this_week = _week_start(now.date())
    weeks = [this_week - timedelta(weeks=i) for i in range(WEEKS - 1, -1, -1)]
    per_week = dict.fromkeys(weeks, 0)
    for when in applied_on.values():
        week = _week_start(when.date())
        if week in per_week:
            per_week[week] += 1

    stages = current_stage_counts(session)
    return DashboardStats(
        flow=_flow(scored, relevant, jobs_inbox, list(reached.values())),
        jobs_inbox=jobs_inbox,
        active=len(reached) - sum(stages.get(key, 0) for key in FINAL_STATUSES),
        interviews=stages.get(INTERVIEW_STATUS, 0),
        offers=stages.get(OFFER_STATUS, 0),
        responded=sum(1 for keys in reached.values() if keys & _RESPONDED),
        applied=count_reaching(APPLIED_STATUS),
        weekly_applied=[WeekCount(week_start=w, count=c) for w, c in per_week.items()],
        upcoming=_upcoming(session, now),
    )


def _upcoming(session: Session, now: datetime) -> list[UpcomingRound]:
    """The next scheduled (planned, dated, not past) interview rounds."""
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
        UpcomingRound(
            application_id=event.application_id,
            job_title=title,
            company=company,
            title=event.title or "",
            round=held.get(event.application_id, 0) + plan_ids[event.application_id].index(event.id) + 1,
            scheduled_at=_as_utc(event.occurred_at),
        )
        for event, title, company in planned
    ]
