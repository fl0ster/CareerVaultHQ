"""Job scraping as a background (RQ) job.

Discovers scraper modules in ``app.tasks.scrape.sources`` and runs them. Every run is
recorded as a ``ScrapeRun`` row; listings whose link is not in the ``jobs`` table yet get
their page's raw HTML fetched and are inserted with a reference to the run that found
them. Parsing details out of the HTML is a separate step: for every inserted job a
``PendingJobParseRun`` row is created and ``app.tasks.parse.parse_job`` is enqueued on the
same queue once the run has been committed.
The returned summary is stored as the RQ job result.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from rq import get_current_job
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import init_db, session_factory
from app.models import Job, PendingJobParseRun, ScrapeRun
from app.queue import get_scrapper_queue
from app.tasks.scrape.description import fetch_page
from app.tasks.scrape.sources import get_available_sources, load_source

log = logging.getLogger(__name__)

PARSE_TIMEOUT = 120


def run_source(name: str) -> dict[str, Any]:
    """Run a single scraper source. Never raises; failures are reported in the result."""
    log.info("=== Running scraper: %s ===", name)
    try:
        module = load_source(name)
        jobs = module.fetch_jobs()
    except Exception as exc:  # noqa: BLE001 - one broken source must not stop the others
        log.exception("Scraper %r failed", name)
        return {"source": name, "ok": False, "error": f"{type(exc).__name__}: {exc}", "jobs": []}
    log.info("Scraper %s returned %d jobs", name, len(jobs))
    return {"source": name, "ok": True, "error": None, "jobs": jobs}


def _resolve_sources(source: str | None) -> list[str]:
    available = get_available_sources()
    if source is None:
        return available
    if source not in available:
        raise ValueError(f"source {source!r} is not available; available: {', '.join(available)}")
    return [source]


def _current_rq_job_id() -> str | None:
    job = get_current_job()
    return job.id if job is not None else None


def save_jobs(
    session: Session, run: ScrapeRun, jobs: list[dict[str, Any]]
) -> tuple[list[PendingJobParseRun], int]:
    """Insert listings not yet in the DB (fetching their page HTML) and return
    ``(pending parse runs for the inserted jobs, duplicates)``. Each inserted job
    references ``run`` and gets a ``NOT_STARTED`` ``PendingJobParseRun``."""
    links = [job["link"] for job in jobs]
    existing: set[str] = set()
    if links:
        existing = set(session.scalars(select(Job.link).where(Job.link.in_(links))))

    pending: list[PendingJobParseRun] = []
    duplicates = 0
    for job in jobs:
        link = job["link"]
        if link in existing:
            duplicates += 1
            continue
        existing.add(link)  # the same link may appear twice in one listing page
        html = fetch_page(link)
        new_job = Job(
            link=link,
            source=job["source"],
            html=html or None,
            scrape_run=run,
        )
        session.add(new_job)
        pending.append(PendingJobParseRun(job=new_job))
    session.add_all(pending)
    return pending, duplicates


def enqueue_parse_jobs(session: Session, pending: list[PendingJobParseRun]) -> list[str]:
    """Enqueue ``parse_job`` for every pending row (which must be committed already) and
    store the RQ job ids on the rows. Returns the RQ job ids."""
    if not pending:
        return []
    # Imported here, not at module level: ``app.tasks.parse.parse`` imports the sources
    # package, whose parent package imports this module, so a top-level import would be
    # circular when the worker imports the parse task first (see test_rq_entrypoints).
    from app.tasks.parse import parse_job

    settings = get_settings()
    queue = get_scrapper_queue()
    ids: list[str] = []
    for row in pending:
        rq_job = queue.enqueue(
            parse_job,
            row.id,
            job_id=uuid.uuid4().hex,
            job_timeout=PARSE_TIMEOUT,
            result_ttl=settings.job_result_ttl,
            failure_ttl=settings.job_result_ttl,
            meta={"pending_id": row.id, "job_id": row.job_id},
            description=f"parse job {row.job_id}",
        )
        row.rq_job_id = rq_job.id
        ids.append(rq_job.id)
    session.commit()
    return ids


def scrape(source: str | None = None) -> dict[str, Any]:
    """Scrape one source (``source``) or all available sources (``None``).

    Returns::

        {
            "scrape_run_id": <id of the ScrapeRun row>,
            "sources": [{"source", "ok", "error", "jobs"}, ...],
            "failed": ["<source name>", ...],
            "jobs": [{"link", "source"}, ...],
            "count": <number of scraped jobs>,
            "new": <jobs inserted into the DB>,
            "duplicates": <jobs already in the DB>,
            "parse_jobs": [<RQ job id of each enqueued parse task>, ...],
        }
    """
    names = _resolve_sources(source)

    init_db()
    with session_factory()() as session:
        run = ScrapeRun(source=source, rq_job_id=_current_rq_job_id())
        session.add(run)
        session.commit()

        try:
            results = [run_source(name) for name in names]
            jobs = [
                {**job, "source": result["source"]} for result in results for job in result["jobs"]
            ]
            pending, duplicates = save_jobs(session, run, jobs)
            new = len(pending)

            failed = [r["source"] for r in results if not r["ok"]]
            run.status = "finished"
            run.scraped_count = len(jobs)
            run.new_count = new
            run.duplicate_count = duplicates
            run.failed_sources = ",".join(failed) or None
        except Exception as exc:
            session.rollback()
            run.status = "failed"
            run.error = f"{type(exc).__name__}: {exc}"
            run.finished_at = datetime.now(UTC)
            session.add(run)
            session.commit()
            raise
        run.finished_at = datetime.now(UTC)
        session.commit()

        # Only enqueue once the jobs and their pending rows are durable, so the parse
        # worker can never pick up an id that does not exist yet.
        parse_ids = enqueue_parse_jobs(session, pending)

        log.info(
            "Scrape run %d: %d scraped, %d new, %d duplicates, failed sources: %s",
            run.id,
            len(jobs),
            new,
            duplicates,
            failed or "none",
        )
        return {
            "scrape_run_id": run.id,
            "sources": results,
            "failed": failed,
            "jobs": jobs,
            "count": len(jobs),
            "new": new,
            "duplicates": duplicates,
            "parse_jobs": parse_ids,
        }
