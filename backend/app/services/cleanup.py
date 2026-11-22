"""Delete old ``jobs`` and ``job_parse_results`` rows; shared by ``DELETE /api/cleanup``
and the daily ``app.tasks.cleanup`` run.

Records created before ``older_than`` are deleted:

* ``job_parse_results`` whose ``parsed_at`` is older than the cut-off.
* ``jobs`` whose discovering scrape run (``scrape_runs.started_at``) is older than the
  cut-off. Jobs have no own timestamp, so jobs without a scrape run are left alone.

Deleting a job cascades (FK ``ON DELETE CASCADE``) to its parse result, pending parse
runs, evaluations and generated CVs. Protected jobs are never deleted, and neither are
their parse results: jobs with a generated CV or an application, and jobs with an evaluation whose
``match_probability`` is at or above ``settings.relevant_job_threshold``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Application, GeneratedCV, Job, JobEvaluation, JobParseResult, ScrapeRun

Target = Literal["all", "jobs", "job_parse_results"]


@dataclass
class CleanupSummary:
    older_than: datetime
    dry_run: bool
    jobs_deleted: int
    job_parse_results_deleted: int


def cleanup_old_jobs(
    session: Session,
    older_than: datetime,
    target: Target = "all",
    dry_run: bool = False,
    relevant_job_threshold: float | None = None,
) -> CleanupSummary:
    if older_than.tzinfo is None:
        older_than = older_than.replace(tzinfo=UTC)
    threshold = get_settings().relevant_job_threshold if relevant_job_threshold is None else relevant_job_threshold

    protected_result_ids = select(GeneratedCV.job_parse_result_id).union(
        select(Application.job_parse_result_id),
        select(JobEvaluation.job_parse_result_id).where(JobEvaluation.match_probability >= threshold),
    )
    protected_job_ids = select(JobParseResult.job_id).where(JobParseResult.id.in_(protected_result_ids))
    old_job_ids = select(Job.id).join(ScrapeRun, Job.scrape_run_id == ScrapeRun.id).where(ScrapeRun.started_at < older_than)

    def _run(model, where) -> int:
        if dry_run:
            return session.scalar(select(func.count()).select_from(model).where(where)) or 0
        return session.execute(delete(model).where(where).execution_options(synchronize_session=False)).rowcount

    results_deleted = 0
    jobs_deleted = 0
    if target in ("all", "job_parse_results"):
        results_deleted = _run(
            JobParseResult,
            (JobParseResult.parsed_at < older_than) & JobParseResult.id.not_in(protected_result_ids),
        )
    if target in ("all", "jobs"):
        jobs_deleted = _run(Job, Job.id.in_(old_job_ids) & Job.id.not_in(protected_job_ids))

    if not dry_run:
        session.commit()
    return CleanupSummary(older_than, dry_run, jobs_deleted, results_deleted)
