"""Numbers behind the Dashboard widgets.

``GET /api/dashboard/stats`` returns, in one request, the job-search funnel (scored jobs
down to accepted offers), a few headline counts, applications sent per week and the next
scheduled interview rounds.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.routes.jobs import inbox_count
from app.config import Settings, get_settings
from app.db import get_session
from app.services import dashboard
from app.services.applications import (
    ACCEPTED_STATUS,
    APPLIED_STATUS,
    FINAL_STATUSES,
    INTERVIEW_STATUS,
    OFFER_STATUS,
    current_stage_counts,
)

router = APIRouter()

WEEKS = 8
"""Weeks shown by the weekly activity widget, the current one included."""


class FunnelStage(BaseModel):
    key: str
    label: str
    count: int


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
    funnel: list[FunnelStage]
    """Widest first: scored jobs, relevant ones, applications, then stages reached."""
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


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


@router.get("/stats", response_model=DashboardStats)
def dashboard_stats(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DashboardStats:
    now = datetime.now(UTC)
    scored, relevant = dashboard.scored_counts(session, settings.relevant_job_threshold)
    total, reached = dashboard.reached_counts(session)

    funnel = [
        FunnelStage(key="SCORED", label="Jobs scored", count=scored),
        FunnelStage(key="RELEVANT", label="Relevant", count=relevant),
        FunnelStage(key="SHORTLISTED", label="Shortlisted", count=total),
        FunnelStage(key=APPLIED_STATUS, label="Applied", count=reached[APPLIED_STATUS]),
        FunnelStage(key=INTERVIEW_STATUS, label="Interviewed", count=reached[INTERVIEW_STATUS]),
        FunnelStage(key=OFFER_STATUS, label="Offer", count=reached[OFFER_STATUS]),
        FunnelStage(key=ACCEPTED_STATUS, label="Accepted", count=reached[ACCEPTED_STATUS]),
    ]

    this_week = _week_start(now.date())
    weeks = [this_week - timedelta(weeks=i) for i in range(WEEKS - 1, -1, -1)]
    per_week = dict.fromkeys(weeks, 0)
    for day, count in dashboard.applied_per_day(session, weeks[0]).items():
        week = _week_start(day)
        if week in per_week:
            per_week[week] += count

    stages = current_stage_counts(session)
    return DashboardStats(
        funnel=funnel,
        jobs_inbox=inbox_count(session, settings.relevant_job_threshold),
        active=total - sum(stages.get(key, 0) for key in FINAL_STATUSES),
        interviews=stages.get(INTERVIEW_STATUS, 0),
        offers=stages.get(OFFER_STATUS, 0),
        responded=reached[dashboard.RESPONDED],
        applied=reached[APPLIED_STATUS],
        weekly_applied=[WeekCount(week_start=w, count=c) for w, c in per_week.items()],
        upcoming=[UpcomingRound(**vars(r)) for r in dashboard.upcoming_rounds(session, now)],
    )
