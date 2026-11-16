"""Parsing a scraped job's raw HTML as a background (RQ) job.

The scrape task inserts a ``PendingJobParseRun`` row for every new ``Job`` and enqueues
``parse_job(pending_id)``. The task looks up the job's ``source.key`` module in
``app.tasks.scrape.sources`` and calls its ``parse_<field>(html, url)`` hook for every
field in ``FIELDS`` (currently ``title``, ``company`` and ``description``). ``title`` and
``description`` are stored verbatim in ``job_parse_results``; the raw ``company`` string is
never stored there but resolved through ``app.services.companies.resolve_company`` to a
canonical ``companies`` row whose id is written to ``job_parse_results.company_id``. The
pending row is then marked ``COMPLETED`` with the time the parse happened. Finally
``app.tasks.evaluate.evaluate_parse_results`` is enqueued for the parsed job so it gets
scored against the current candidate profile.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from types import ModuleType
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import init_db, session_factory
from app.models import Job, JobParseResult, PendingJobParseRun
from app.queue import get_queue
from app.services.companies import CompanyMatch, resolve_company
from app.tasks.evaluate import evaluate_parse_results
from app.tasks.scrape.sources import load_source

log = logging.getLogger(__name__)

EVALUATE_TIMEOUT = 300
"""RQ ``job_timeout`` for the evaluation enqueued after a parse (one OpenRouter call)."""


FIELDS = ("title", "company", "description")
"""Fields extracted by the source's ``parse_<field>(html, url)`` hook. All but ``company``
are columns of ``JobParseResult``; ``company`` is resolved to ``company_id``."""

TEXT_FIELDS = tuple(field for field in FIELDS if field != "company")
"""The fields of ``FIELDS`` stored verbatim on ``JobParseResult``."""


class JobParseError(RuntimeError):
    """The job cannot be parsed (no HTML, unknown source, source has no parser)."""


def _source_module(job: Job) -> ModuleType:
    try:
        return load_source(job.source.key)
    except ValueError as exc:
        raise JobParseError(str(exc)) from exc


def parse_field(job: Job, field: str, module: ModuleType | None = None) -> str:
    """Dispatch to ``app.tasks.scrape.sources.<job.source.key>.parse_<field>(html)``."""
    if not job.html:
        raise JobParseError(f"job {job.id} has no HTML to parse")
    module = module or _source_module(job)
    parser = getattr(module, f"parse_{field}", None)
    if parser is None:
        raise JobParseError(f"source {job.source.key!r} does not define parse_{field}")
    return parser(job.html)


def parse_title(job: Job) -> str:
    return parse_field(job, "title")


def parse_company(job: Job) -> str:
    return parse_field(job, "company")


def parse_description(job: Job) -> str:
    return parse_field(job, "description")


def parse_fields(job: Job) -> dict[str, str]:
    """``{field: value}`` for every field in ``FIELDS``."""
    module = _source_module(job)
    return {field: parse_field(job, field, module) for field in FIELDS}


def _save_result(
    session: Session, job: Job, values: dict[str, str]
) -> tuple[JobParseResult, CompanyMatch | None]:
    """Upsert the ``JobParseResult`` of ``job``; the ``company`` value goes through the
    company ingestion pipeline and only the canonical ``company_id`` is stored."""
    result = session.scalar(select(JobParseResult).where(JobParseResult.job_id == job.id))
    if result is None:
        result = JobParseResult(job_id=job.id)
        session.add(result)
    for field in TEXT_FIELDS:
        setattr(result, field, values.get(field) or None)
    match = resolve_company(session, values.get("company", ""), source=job.source)
    result.company = match.company if match else None
    result.parsed_at = datetime.now(UTC)
    return result, match


def enqueue_evaluation(result: JobParseResult) -> str | None:
    """Enqueue ``evaluate_parse_results([result.id])`` (``result`` must be committed) and return the
    RQ job id. Failing to reach Redis is logged, not raised: the parse itself succeeded
    and a later ``evaluate_pending_jobs()`` run picks the job up anyway."""
    settings = get_settings()
    try:
        rq_job = get_queue().enqueue(
            evaluate_parse_results,
            [result.id],
            job_id=uuid.uuid4().hex,
            job_timeout=EVALUATE_TIMEOUT,
            result_ttl=settings.job_result_ttl,
            failure_ttl=settings.job_result_ttl,
            meta={"job_parse_result_id": result.id, "job_id": result.job_id},
            description=f"evaluate job {result.job_id}",
        )
    except Exception:
        log.exception("Could not enqueue evaluation of job %d", result.job_id)
        return None
    return rq_job.id


def parse_job(pending_id: int) -> dict[str, Any]:
    """Parse the job referenced by ``pending_job_parse_runs.id == pending_id``.

    Returns::

        {
            "pending_id": <id of the PendingJobParseRun row>,
            "job_id": <id of the parsed Job>,
            "source": "<source module name>",
            "title": "<extracted title>",
            "company": "<canonical company name, or None>",
            "company_id": <id of the canonical companies row, or None>,
            "company_match": "<alias | exact | fuzzy | new, or None>",
            "description_chars": <length of the extracted description>,
            "evaluate_job": "<RQ job id of the enqueued evaluation, or None>",
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
        if job is None:
            raise ValueError(f"pending parse run {pending_id} references a missing job")

        if pending.status == PendingJobParseRun.STATUS_COMPLETED:
            log.info("Job %d was already parsed", job.id)
            result = session.scalar(select(JobParseResult).where(JobParseResult.job_id == job.id))
            company = result.company if result else None
            return {
                "pending_id": pending.id,
                "job_id": job.id,
                "source": job.source.key,
                "title": result.title if result else None,
                "company": company.name if company else None,
                "company_id": company.id if company else None,
                "company_match": None,
                "description_chars": len(result.description or "") if result else 0,
                "evaluate_job": None,
            }

        try:
            values = parse_fields(job)
            result, match = _save_result(session, job, values)
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
        evaluate_job_id = enqueue_evaluation(result)

        company = match.company if match else None
        log.info(
            "Parsed job %d (%s): %r at %r (company %s, %s), %d chars",
            job.id,
            job.link,
            values["title"],
            values["company"],
            company.id if company else None,
            match.match_kind if match else "none",
            len(values["description"]),
        )
        return {
            "pending_id": pending.id,
            "job_id": job.id,
            "source": job.source.key,
            "title": values["title"],
            "company": company.name if company else None,
            "company_id": company.id if company else None,
            "company_match": match.match_kind if match else None,
            "description_chars": len(values["description"]),
            "evaluate_job": evaluate_job_id,
        }
