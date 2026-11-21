"""Scrape sources: the ``scrape_sources`` rows that mirror the plugin modules in
``app.tasks.scrape.sources``.

``sync_sources`` is the bridge between the two worlds. It is called before every scrape run
and by ``GET /api/sources``: every discovered module gets a row (``key`` = module name),
existing rows are refreshed with the module's ``NAME``/``URL``/contract state, and rows
whose module has disappeared are kept but marked ``module_error = "module not found"``.
Rows are never deleted because ``jobs`` reference them.

``apply_run_result`` records the outcome of one source's scrape on its row (the task calls
it after each source) and ``source_relevance`` aggregates how well each source's jobs match
the current candidate profile.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import CandidateProfile, Job, JobEvaluation, JobParseResult, ScrapeSource
from app.tasks.scrape.sources import discover_sources

GOOD_MATCH_PROBABILITY = 0.5
"""A ``job_evaluations.match_probability`` at or above this counts as a good match."""


def _ordered(query):
    """Sources are always listed (and run by "scrape all") by ``key``."""
    return query.order_by(ScrapeSource.key)


def list_sources(session: Session) -> list[ScrapeSource]:
    return list(session.scalars(_ordered(select(ScrapeSource))).all())


def runnable_sources(session: Session) -> list[ScrapeSource]:
    """Sources a "scrape all" run executes: enabled and with a usable module."""
    return list(
        session.scalars(
            _ordered(
                select(ScrapeSource).where(
                    ScrapeSource.enabled.is_(True), ScrapeSource.module_error.is_(None)
                )
            )
        ).all()
    )


def get_source(session: Session, key: str) -> ScrapeSource | None:
    return session.scalar(select(ScrapeSource).where(ScrapeSource.key == key))


def sync_sources(session: Session) -> list[ScrapeSource]:
    """Upsert a row per discovered module and return every row (ordered). Commits.

    The API and the worker may sync at the same time; ``key`` is unique, so the loser of a
    concurrent insert rolls back and simply re-reads the rows the winner committed.
    """
    discovered = {info.key: info for info in discover_sources()}
    rows = {row.key: row for row in session.scalars(select(ScrapeSource)).all()}

    for key, info in discovered.items():
        row = rows.get(key)
        if row is None:
            row = ScrapeSource(key=key)
            # Hand-entered jobs (``sources/manual.py``) have nothing to scrape.
            if key == "manual":
                row.enabled = False
            session.add(row)
        row.name = info.name
        row.url = info.url
        row.module_error = info.error
    for key, row in rows.items():
        if key not in discovered:
            row.module_error = ScrapeSource.MODULE_MISSING

    try:
        session.commit()
    except IntegrityError:
        session.rollback()
    return list_sources(session)


def apply_run_result(
    row: ScrapeSource,
    *,
    ok: bool,
    error: str | None,
    scraped: int,
    new: int,
    now: datetime | None = None,
) -> None:
    """Record the outcome of one scrape of ``row`` (the caller commits)."""
    now = now or datetime.now(UTC)
    row.last_run_at = now
    row.last_scraped_count = scraped
    row.last_new_count = new
    row.last_error = None if ok else (error or "failed")
    if ok:
        row.last_success_at = now
        row.consecutive_failures = 0
    else:
        row.consecutive_failures = (row.consecutive_failures or 0) + 1


@dataclass(frozen=True)
class Relevance:
    """How a source's jobs score against the latest candidate profile."""

    job_count: int = 0
    """Jobs scraped from the source (evaluated or not)."""
    evaluated_count: int = 0
    """Jobs with a ``job_evaluations`` row for the latest profile."""
    avg_match: float | None = None
    """Mean ``match_probability`` over the evaluated jobs (``None`` when none)."""
    good_match_share: float | None = None
    """Share (0-1) of evaluated jobs at or above ``GOOD_MATCH_PROBABILITY``."""


def source_relevance(session: Session) -> dict[int, Relevance]:
    """``{scrape_sources.id: Relevance}`` for every source that has at least one job."""
    latest = select(func.max(CandidateProfile.id)).scalar_subquery()
    counts = dict(
        session.execute(select(Job.source_id, func.count()).group_by(Job.source_id)).all()
    )
    evaluated = session.execute(
        select(
            Job.source_id,
            func.count(JobEvaluation.id),
            func.avg(JobEvaluation.match_probability),
            func.sum(
                case((JobEvaluation.match_probability >= GOOD_MATCH_PROBABILITY, 1), else_=0)
            ),
        )
        .join(JobParseResult, JobParseResult.job_id == Job.id)
        .join(
            JobEvaluation,
            (JobEvaluation.job_parse_result_id == JobParseResult.id)
            & (JobEvaluation.candidate_profile_id == latest),
        )
        .group_by(Job.source_id)
    ).all()

    result = {source_id: Relevance(job_count=total) for source_id, total in counts.items()}
    for source_id, n, avg, good in evaluated:
        if not n:
            continue
        result[source_id] = Relevance(
            job_count=counts.get(source_id, 0),
            evaluated_count=n,
            avg_match=float(avg),
            good_match_share=(good or 0) / n,
        )
    return result
