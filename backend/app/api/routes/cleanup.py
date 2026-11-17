"""``DELETE /api/cleanup``: remove old jobs and job parse results.

``older_than`` is a cut-off datetime. Records created before it are deleted:

* ``job_parse_results`` whose ``parsed_at`` is older than the cut-off.
* ``jobs`` whose discovering scrape run (``scrape_runs.started_at``) is older than the
  cut-off. Jobs have no own timestamp, so jobs without a scrape run are left alone.

Deleting a job cascades (FK ``ON DELETE CASCADE``) to its parse result, pending parse
runs, evaluations and generated CVs. Protected jobs are never deleted, and neither are
their parse results: jobs with a generated CV, and jobs with an evaluation whose
``match_probability`` is at or above ``settings.relevant_job_threshold``.
Pass ``dry_run=true`` to only count the matches.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.models import GeneratedCV, Job, JobEvaluation, JobParseResult, ScrapeRun

router = APIRouter()

Target = Literal["all", "jobs", "job_parse_results"]


class CleanupResult(BaseModel):
    older_than: datetime
    dry_run: bool
    jobs_deleted: int
    job_parse_results_deleted: int


@router.delete("", response_model=CleanupResult)
def cleanup(
    session: Annotated[Session, Depends(get_session)],
    older_than: Annotated[
        datetime, Query(description="Delete records created before this datetime (ISO 8601)")
    ],
    target: Target = "all",
    dry_run: bool = False,
) -> CleanupResult:
    if older_than.tzinfo is None:
        older_than = older_than.replace(tzinfo=UTC)

    threshold = get_settings().relevant_job_threshold
    protected_result_ids = select(GeneratedCV.job_parse_result_id).union(
        select(JobEvaluation.job_parse_result_id).where(
            JobEvaluation.match_probability >= threshold
        )
    )
    protected_job_ids = select(JobParseResult.job_id).where(
        JobParseResult.id.in_(protected_result_ids)
    )

    old_job_ids = (
        select(Job.id)
        .join(ScrapeRun, Job.scrape_run_id == ScrapeRun.id)
        .where(ScrapeRun.started_at < older_than)
    )

    jobs_deleted = 0
    results_deleted = 0

    if target in ("all", "job_parse_results"):
        where = (JobParseResult.parsed_at < older_than) & JobParseResult.id.not_in(
            protected_result_ids
        )
        if dry_run:
            results_deleted = (
                session.scalar(select(func.count()).where(where).select_from(JobParseResult)) or 0
            )
        else:
            results_deleted = session.execute(
                delete(JobParseResult).where(where).execution_options(synchronize_session=False)
            ).rowcount

    if target in ("all", "jobs"):
        where = Job.id.in_(old_job_ids) & Job.id.not_in(protected_job_ids)
        if dry_run:
            jobs_deleted = session.scalar(select(func.count()).where(where).select_from(Job)) or 0
        else:
            jobs_deleted = session.execute(
                delete(Job).where(where).execution_options(synchronize_session=False)
            ).rowcount

    if not dry_run:
        session.commit()

    return CleanupResult(
        older_than=older_than,
        dry_run=dry_run,
        jobs_deleted=jobs_deleted,
        job_parse_results_deleted=results_deleted,
    )
