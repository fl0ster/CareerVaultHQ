"""Job scraping as a background (RQ) job.

Discovers scraper modules in ``app.tasks.scrape.sources`` and runs them. Every run is
recorded as a ``ScrapeRun`` row; listings whose link is not in the ``jobs`` table yet get
their description fetched and are inserted with a reference to the run that found them.
The returned summary is stored as the RQ job result.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from rq import get_current_job
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import init_db, session_factory
from app.models import Job, ScrapeRun
from app.tasks.scrape.description import fetch_description
from app.tasks.scrape.sources import get_available_sources, load_source

log = logging.getLogger(__name__)


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


def save_jobs(session: Session, run: ScrapeRun, jobs: list[dict[str, Any]]) -> tuple[int, int]:
    """Insert listings not yet in the DB (fetching their description) and return
    ``(new, duplicates)``. Each inserted job references ``run``."""
    links = [job["link"] for job in jobs]
    existing: set[str] = set()
    if links:
        existing = set(session.scalars(select(Job.link).where(Job.link.in_(links))))

    new = duplicates = 0
    for job in jobs:
        link = job["link"]
        if link in existing:
            duplicates += 1
            continue
        existing.add(link)  # the same link may appear twice in one listing page
        description = fetch_description(link)
        session.add(
            Job(
                title=job["title"],
                link=link,
                date_added=job.get("date_added") or "",
                source=job["source"],
                description=description or None,
                scrape_run=run,
            )
        )
        new += 1
    return new, duplicates


def scrape(source: str | None = None) -> dict[str, Any]:
    """Scrape one source (``source``) or all available sources (``None``).

    Returns::

        {
            "scrape_run_id": <id of the ScrapeRun row>,
            "sources": [{"source", "ok", "error", "jobs"}, ...],
            "failed": ["<source name>", ...],
            "jobs": [{"title", "link", "date_added", "source"}, ...],
            "count": <number of scraped jobs>,
            "new": <jobs inserted into the DB>,
            "duplicates": <jobs already in the DB>,
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
            new, duplicates = save_jobs(session, run, jobs)

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
        }
