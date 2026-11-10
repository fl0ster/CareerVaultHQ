"""Scraped jobs stored in the database.

``GET /api/jobs?offset=0&limit=50`` returns a page of jobs, newest first (by the time
they were added to the database), together with ``total`` and ``has_more`` so clients
can load further pages progressively.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Job

router = APIRouter()

MAX_PAGE_SIZE = 200


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    link: str
    date_added: str
    source: str
    scraped_at: datetime
    scrape_run_id: int | None
    has_description: bool = False


class JobDetail(JobOut):
    description: str | None


class JobPage(BaseModel):
    items: list[JobOut]
    total: int
    offset: int
    limit: int
    has_more: bool


def _to_out(job: Job) -> JobOut:
    out = JobOut.model_validate(job)
    out.has_description = bool(job.description)
    return out


@router.get("", response_model=JobPage)
def list_jobs(
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
    jobs = session.scalars(
        query.order_by(Job.scraped_at.desc(), Job.id.desc()).offset(offset).limit(limit)
    ).all()
    return JobPage(
        items=[_to_out(j) for j in jobs],
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + len(jobs) < total,
    )


@router.get("/{job_id}", response_model=JobDetail)
def get_job(job_id: int, session: Annotated[Session, Depends(get_session)]) -> JobDetail:
    """A single scraped job including its full description."""
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown job")
    detail = JobDetail.model_validate(job)
    detail.has_description = bool(job.description)
    return detail
