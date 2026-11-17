"""The Timeline: a chronological log of events plus the user's read cursor.

``GET /api/timeline/events`` pages events in ascending ``id`` order (``after_id``,
``before_id`` or ``around_id``), ``GET /api/timeline/status`` reports the newest event and
the unread counts, and ``PUT /api/timeline/read`` moves the read cursor forward.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.models import (
    Application,
    CandidateProfile,
    Company,
    JobEvaluation,
    JobParseResult,
    TimelineEvent,
)
from app.services import timeline
from app.services.relevance import relevance

router = APIRouter()

MAX_PAGE_SIZE = 200


class TimelineEventOut(BaseModel):
    id: int
    type: str
    occurred_at: datetime
    job_id: int | None
    scrape_run_id: int | None
    source_id: int | None
    payload: dict[str, Any]
    relevant: bool | None = None
    """For job events: ``match_probability`` at or above the relevance threshold."""
    relevance: float | None = None
    """For job events: the score on the [-1, 1] display scale (0 at the threshold)."""

    company_id: int | None = None
    """Job events: the job's company now (live, not from the snapshot)."""
    company_tag: str | None = None
    """Job events: the company's current tag."""
    evaluation_id: int | None = None
    """Job events: the job's evaluation against the latest profile (to apply with)."""
    application_id: int | None = None
    """Job events: the application created for the job, if any."""

    @field_validator("occurred_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        # SQLite drops the timezone; stored values are UTC.
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class TimelinePageOut(BaseModel):
    events: list[TimelineEventOut]
    has_older: bool
    has_newer: bool


class TimelineStatusOut(BaseModel):
    latest_id: int
    last_read_id: int
    unread: int
    unread_relevant: int


class MarkReadIn(BaseModel):
    event_id: int


def _event_out(event: TimelineEvent, threshold: float) -> TimelineEventOut:
    out = TimelineEventOut(
        id=event.id,
        type=event.type,
        occurred_at=event.occurred_at,
        job_id=event.job_id,
        scrape_run_id=event.scrape_run_id,
        source_id=event.source_id,
        payload=event.payload or {},
    )
    probability = out.payload.get("match_probability")
    if probability is not None:
        out.relevant = probability >= threshold
        out.relevance = relevance(probability, threshold)
    return out


class _JobContext(BaseModel):
    company_id: int | None
    company_tag: str | None
    evaluation_id: int | None
    application_id: int | None


def _job_context(session: Session, job_ids: list[int]) -> dict[int, _JobContext]:
    """Current state of the given jobs that the snapshot cannot hold: company tag, the
    evaluation an application would be created from and an existing application."""
    if not job_ids:
        return {}
    profile_id = session.scalar(select(func.max(CandidateProfile.id)))
    rows = session.execute(
        select(
            JobParseResult.job_id,
            JobParseResult.company_id,
            Company.tag,
            JobEvaluation.id,
            Application.id,
        )
        .outerjoin(Company, Company.id == JobParseResult.company_id)
        .outerjoin(
            JobEvaluation,
            (JobEvaluation.job_parse_result_id == JobParseResult.id)
            & (JobEvaluation.candidate_profile_id == profile_id),
        )
        .outerjoin(Application, Application.job_parse_result_id == JobParseResult.id)
        .where(JobParseResult.job_id.in_(job_ids))
    ).all()
    return {
        job_id: _JobContext(
            company_id=company_id,
            company_tag=tag,
            evaluation_id=evaluation_id,
            application_id=application_id,
        )
        for job_id, company_id, tag, evaluation_id, application_id in rows
    }


@router.get("/events", response_model=TimelinePageOut)
def list_events(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    after_id: int | None = None,
    before_id: int | None = None,
    around_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
) -> TimelinePageOut:
    result = timeline.page(
        session, after_id=after_id, before_id=before_id, around_id=around_id, limit=limit
    )
    threshold = settings.relevant_job_threshold
    context = _job_context(session, [e.job_id for e in result.events if e.job_id is not None])
    events = []
    for event in result.events:
        out = _event_out(event, threshold)
        job = context.get(event.job_id) if event.job_id is not None else None
        if job is not None:
            out = out.model_copy(update=job.model_dump())
        events.append(out)
    return TimelinePageOut(
        events=events,
        has_older=result.has_older,
        has_newer=result.has_newer,
    )


@router.get("/status", response_model=TimelineStatusOut)
def get_status(session: Annotated[Session, Depends(get_session)]) -> TimelineStatusOut:
    return TimelineStatusOut(**vars(timeline.status(session)))


@router.put("/read", response_model=TimelineStatusOut)
def mark_read(
    body: MarkReadIn, session: Annotated[Session, Depends(get_session)]
) -> TimelineStatusOut:
    timeline.mark_read(session, body.event_id)
    return TimelineStatusOut(**vars(timeline.status(session)))
