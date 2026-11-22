"""Looking up the scores (``job_evaluations``) shown for parsed jobs."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models import JobEvaluation


def newest_evaluations(session: Session, parse_result_ids: list[int]) -> dict[int, JobEvaluation]:
    """``{job_parse_result_id: newest JobEvaluation}`` for those of ``parse_result_ids`` that
    were scored, whichever profile the newest score was made against (a re-score is always
    the newest one)."""
    if not parse_result_ids:
        return {}
    newest_ids = (
        select(func.max(JobEvaluation.id))
        .where(JobEvaluation.job_parse_result_id.in_(parse_result_ids))
        .group_by(JobEvaluation.job_parse_result_id)
    )
    rows = session.scalars(
        select(JobEvaluation).where(JobEvaluation.id.in_(newest_ids)).options(joinedload(JobEvaluation.openrouter_call))
    )
    return {e.job_parse_result_id: e for e in rows}
