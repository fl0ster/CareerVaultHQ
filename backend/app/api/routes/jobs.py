"""Jobs stored in the database.

``GET /api/jobs?offset=0&limit=50`` returns a page of **evaluated** jobs: every
``job_evaluations`` row made against the latest candidate profile, together with the
job's parsed details (title, company, ...) and the scraped link. ``GET /api/jobs/{job_id}``
returns one job with its full parsed description.

The raw scraped rows (``jobs`` table, including the fetched html) are still available
under ``GET /api/jobs/raw`` and ``GET /api/jobs/raw/{job_id}``.

Every list endpoint returns ``total`` and ``has_more`` so clients can load further pages
progressively.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, joinedload

from app.db import get_session
from app.models import CandidateProfile, Job, JobEvaluation, JobParseResult

router = APIRouter()

MAX_PAGE_SIZE = 200

SortOrder = Literal["newest", "match"]


# --- raw scraped jobs -----------------------------------------------------------------


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    link: str
    source: str
    scrape_run_id: int | None
    has_html: bool = False


class JobFull(JobOut):
    html: str | None


class JobPage(BaseModel):
    items: list[JobOut]
    total: int
    offset: int
    limit: int
    has_more: bool


def _to_out(job: Job) -> JobOut:
    out = JobOut.model_validate(job)
    out.has_html = bool(job.html)
    return out


@router.get("/raw", response_model=JobPage)
def list_raw_jobs(
    session: Annotated[Session, Depends(get_session)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
    source: str | None = None,
) -> JobPage:
    """Page of scraped jobs, newest first. Optionally filtered by scraper ``source``."""
    query = select(Job)
    count_query = select(func.count()).select_from(Job)
    if source:
        query = query.where(Job.source == source)
        count_query = count_query.where(Job.source == source)

    total = session.scalar(count_query) or 0
    jobs = session.scalars(query.order_by(Job.id.desc()).offset(offset).limit(limit)).all()
    return JobPage(
        items=[_to_out(j) for j in jobs],
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + len(jobs) < total,
    )


@router.get("/raw/{job_id}", response_model=JobFull)
def get_raw_job(job_id: int, session: Annotated[Session, Depends(get_session)]) -> JobFull:
    """A single scraped job including its full html content."""
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown job")
    return JobFull.model_validate(job)


# --- evaluated jobs -------------------------------------------------------------------


class EvaluationOut(BaseModel):
    id: int
    candidate_profile_id: int
    match_probability: float
    model: str | None
    """Model that produced the score (from the ``openrouter_calls`` row), if still known."""
    created_at: datetime


def _evaluation_out(evaluation: JobEvaluation | None) -> EvaluationOut | None:
    if evaluation is None:
        return None
    call = evaluation.openrouter_call
    return EvaluationOut(
        id=evaluation.id,
        candidate_profile_id=evaluation.candidate_profile_id,
        match_probability=evaluation.match_probability,
        model=call.model if call is not None else None,
        created_at=evaluation.created_at,
    )


class EvaluatedJobOut(BaseModel):
    """One evaluated job: the scraped row, its parsed details and the score."""

    id: int
    """``jobs.id``"""
    link: str
    source: str
    scrape_run_id: int | None
    has_html: bool
    title: str | None
    company: str | None
    parsed_at: datetime
    evaluation: EvaluationOut


class EvaluatedJobDetail(EvaluatedJobOut):
    description: str | None
    evaluation: EvaluationOut | None
    """``None`` when the job is parsed but not yet scored against the latest profile."""


class EvaluatedJobPage(BaseModel):
    items: list[EvaluatedJobOut]
    total: int
    offset: int
    limit: int
    has_more: bool
    candidate_profile_id: int | None
    """Profile the evaluations were made against; ``None`` when no profile exists yet."""


def _latest_profile_id(session: Session) -> int | None:
    return session.scalar(select(func.max(CandidateProfile.id)))


def _evaluated(
    job: Job, parsed: JobParseResult, evaluation: JobEvaluation | None, *, description: bool
) -> dict:
    data = {
        "id": job.id,
        "link": job.link,
        "source": job.source,
        "scrape_run_id": job.scrape_run_id,
        "has_html": bool(job.html),
        "title": parsed.title,
        "company": parsed.company.name if parsed.company is not None else None,
        "parsed_at": parsed.parsed_at,
        "evaluation": _evaluation_out(evaluation),
    }
    if description:
        data["description"] = parsed.description
    return data


def _evaluated_query(profile_id: int) -> Select:
    return (
        select(Job, JobParseResult, JobEvaluation)
        .join(JobParseResult, JobParseResult.job_id == Job.id)
        .join(JobEvaluation, JobEvaluation.job_parse_result_id == JobParseResult.id)
        .where(JobEvaluation.candidate_profile_id == profile_id)
        .options(joinedload(JobParseResult.company), joinedload(JobEvaluation.openrouter_call))
    )


@router.get("", response_model=EvaluatedJobPage)
def list_jobs(
    session: Annotated[Session, Depends(get_session)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
    source: str | None = None,
    min_probability: Annotated[float | None, Query(ge=0, le=1)] = None,
    sort: SortOrder = "newest",
) -> EvaluatedJobPage:
    """Page of jobs evaluated against the latest candidate profile.

    ``sort=newest`` (default) lists the most recently evaluated first; ``sort=match`` lists
    the best matches first. ``min_probability`` keeps only jobs scored at or above it.
    """
    profile_id = _latest_profile_id(session)
    if profile_id is None:
        return EvaluatedJobPage(
            items=[], total=0, offset=offset, limit=limit, has_more=False, candidate_profile_id=None
        )

    query = _evaluated_query(profile_id)
    if source:
        query = query.where(Job.source == source)
    if min_probability is not None:
        query = query.where(JobEvaluation.match_probability >= min_probability)

    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    if sort == "match":
        query = query.order_by(JobEvaluation.match_probability.desc(), JobEvaluation.id.desc())
    else:
        query = query.order_by(JobEvaluation.id.desc())
    rows = session.execute(query.offset(offset).limit(limit)).all()
    items = [
        EvaluatedJobOut(**_evaluated(job, parsed, evaluation, description=False))
        for job, parsed, evaluation in rows
    ]
    return EvaluatedJobPage(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + len(items) < total,
        candidate_profile_id=profile_id,
    )


@router.get("/{job_id}", response_model=EvaluatedJobDetail)
def get_job(job_id: int, session: Annotated[Session, Depends(get_session)]) -> EvaluatedJobDetail:
    """A single parsed job with its full description and its score against the latest
    candidate profile (``evaluation`` is ``null`` when it has not been scored yet).

    404 when the job does not exist or has not been parsed.
    """
    row = session.execute(
        select(Job, JobParseResult)
        .join(JobParseResult, JobParseResult.job_id == Job.id)
        .where(Job.id == job_id)
        .options(joinedload(JobParseResult.company))
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown or unparsed job")
    job, parsed = row

    evaluation = None
    profile_id = _latest_profile_id(session)
    if profile_id is not None:
        evaluation = session.scalars(
            select(JobEvaluation).where(
                JobEvaluation.job_parse_result_id == parsed.id,
                JobEvaluation.candidate_profile_id == profile_id,
            )
        ).first()
    return EvaluatedJobDetail(**_evaluated(job, parsed, evaluation, description=True))
