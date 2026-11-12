"""Parsing a scraped job's raw HTML as a background (RQ) job.

The scrape task inserts a ``PendingJobParseRun`` row for every new ``Job`` and enqueues
``parse_job(pending_id)``. The task looks up the job's ``source`` module in
``app.tasks.scrape.sources`` and calls its ``parse_description(html, url)``; the text is
stored in ``job_parse_results`` and the pending row is marked ``COMPLETED`` with the time
the parse happened. For now only the description is extracted.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import init_db, session_factory
from app.models import Job, JobParseResult, PendingJobParseRun
from app.tasks.scrape.sources import load_source

log = logging.getLogger(__name__)


class JobParseError(RuntimeError):
    """The job cannot be parsed (no HTML, unknown source, source has no parser)."""


def parse_description(job: Job) -> str:
    """Dispatch to ``app.tasks.scrape.sources.<job.source>.parse_description``."""
    if not job.html:
        raise JobParseError(f"job {job.id} has no HTML to parse")
    try:
        module = load_source(job.source)
    except ValueError as exc:
        raise JobParseError(str(exc)) from exc
    parser = getattr(module, "parse_description", None)
    if parser is None:
        raise JobParseError(f"source {job.source!r} does not define parse_description")
    return parser(job.html, job.link)


def _save_result(session: Session, job: Job, description: str) -> JobParseResult:
    result = session.scalar(select(JobParseResult).where(JobParseResult.job_id == job.id))
    if result is None:
        result = JobParseResult(job_id=job.id)
        session.add(result)
    result.description = description or None
    result.parsed_at = datetime.now(UTC)
    return result


def parse_job(pending_id: int) -> dict[str, Any]:
    """Parse the job referenced by ``pending_job_parse_runs.id == pending_id``.

    Returns::

        {
            "pending_id": <id of the PendingJobParseRun row>,
            "job_id": <id of the parsed Job>,
            "source": "<source module name>",
            "description_chars": <length of the extracted description>,
        }

    Raises on failure after marking the pending row ``FAILED`` so RQ records the job as
    failed and the error is visible in the database as well.
    """
    init_db()
    with session_factory()() as session:
        pending = session.get(PendingJobParseRun, pending_id)
        
        if pending is None:
            raise ValueError(f"unknown pending parse run: {pending_id}")

        job = session.get(Job, pending.job_id)
        if pending.status == PendingJobParseRun.STATUS_COMPLETED:
            log.info("Job %d was already parsed", job.id)
            return {
                "pending_id": pending.id,
                "job_id": job.id,
                "source": job.source,
                "description_chars": len(job.description),
            }
        
        if job is None:
            raise ValueError(f"pending parse run {pending_id} references a missing job")        

        try:
            description = parse_description(job)
            _save_result(session, job, description)
        except Exception as exc:
            session.rollback()
            pending.status = PendingJobParseRun.STATUS_FAILED
            pending.error = f"{type(exc).__name__}: {exc}"
            pending.parsed_at = datetime.now(UTC)
            session.add(pending)
            session.commit()
            log.exception("Parsing job %d (%s) failed", job.id, job.link)
            raise

        pending.status = PendingJobParseRun.STATUS_COMPLETED
        pending.error = None
        pending.parsed_at = datetime.now(UTC)
        session.commit()

        log.info("Parsed job %d (%s): %d chars", job.id, job.link, len(description))
        return {
            "pending_id": pending.id,
            "job_id": job.id,
            "source": job.source,
            "description_chars": len(description),
        }
