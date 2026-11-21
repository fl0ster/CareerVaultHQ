"""Job scraping as a background (RQ) job.

Runs the scraper plugins in ``app.tasks.scrape.sources`` through their ``scrape_sources``
rows (``app.services.sources``): the rows are synced from the modules first, a "scrape all"
run takes the enabled, importable sources (by key), and a run limited to one
source takes that row even when it is disabled (so a fix can be tested by hand).

Every run is recorded as a ``ScrapeRun`` row; listings whose link is not in the ``jobs``
table yet get their page's raw HTML fetched and are inserted with a reference to the run and
to the source. After each source its row's health bookkeeping (``last_run_at``,
``consecutive_failures``, ...) is updated and committed, so a long multi-source run loses
nothing when a later source crashes the worker. Parsing details out of the HTML is a separate
step: for every inserted job a ``PendingJobParseRun`` row is created and
``app.tasks.parse.parse_job`` is enqueued on the same queue once the run has been committed.
The returned summary is stored as the RQ job result.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime
from types import ModuleType
from typing import Any
from urllib.parse import urlparse

import httpx
from rq import Queue, get_current_job
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import init_db, session_factory
from app.models import (
    Job,
    PendingJobParseRun,
    ScrapeRun,
    ScrapeSource,
)
from app.queue import get_queue
from app.services.companies import normalize_company_name
from app.services.sources import (
    apply_run_result,
    get_source,
    is_scrape_target,
    runnable_sources,
    sync_sources,
)
from app.tasks.scrape._helpers import FETCH_TIMEOUT, HEADERS
from app.tasks.scrape.sources import load_source

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
    return {"source": name, "ok": True, "error": None, "jobs": jobs, "module": module}


def _resolve_sources(session: Session, source: str | None) -> list[ScrapeSource]:
    """Rows to run: every enabled, usable source for ``None``; the named source otherwise
    (disabled is fine, a missing or broken module is not)."""
    rows = sync_sources(session)
    if source is None:
        return runnable_sources(session)
    row = get_source(session, source)
    if row is not None and not is_scrape_target(row):
        row = None
    if row is None or row.module_error is not None:
        available = ", ".join(r.key for r in rows if r.module_error is None and is_scrape_target(r))
        reason = f" ({row.module_error})" if row is not None else ""
        raise ValueError(f"source {source!r} is not available{reason}; available: {available}")
    return [row]


def _current_rq_job_id() -> str | None:
    job = get_current_job()
    return job.id if job is not None else None


def fetch_html(url: str) -> str:
    resp = httpx.get(url, headers=HEADERS, follow_redirects=True, timeout=FETCH_TIMEOUT)
    resp.raise_for_status()
    return resp.text


def fetch_page(url: str) -> str:
    """Raw HTML of a job page; ``""`` when it could not be fetched."""
    html = ""
    try:
        html = fetch_html(url)
    except Exception as exc:  # noqa: BLE001 - a missing page must not fail the run
        log.warning("fetch %s: %s", url, exc)
    return html


def normalize_title(title: str | None) -> str:
    """Title as searched and compared for duplicates: whitespace collapsed, lowercased."""
    return re.sub(r"\s+", " ", title or "").strip().lower()


def link_domain(link: str) -> str:
    """Domain of ``link``, lowercased and without a leading ``www.``."""
    return urlparse(link).netloc.lower().removeprefix("www.")


OfferKey = tuple[str, str, str]
"""``(link domain, normalized title, normalized company)`` identifying an offer."""


def _parse_field(module: ModuleType | None, field: str, html: str) -> str:
    """``module.parse_<field>(html)``; ``""`` when there is no page, no parser, or the
    parser fails. Pure HTML parsing, no database access."""
    parser = getattr(module, f"parse_{field}", None)
    if not html or parser is None:
        return ""
    try:
        return parser(html) or ""
    except Exception as exc:  # noqa: BLE001 - a parser bug must not fail the run
        log.warning("parse_%s failed during dedupe: %s", field, exc)
        return ""


def offer_key(module: ModuleType | None, link: str, html: str) -> OfferKey | None:
    """Duplicate-detection key of a fetched job page, or ``None`` when its title or
    company cannot be parsed (such jobs are never deduplicated)."""
    title = normalize_title(_parse_field(module, "title", html))
    company = normalize_company_name(_parse_field(module, "company", html))
    if not title or not company:
        return None
    return link_domain(link), title, company


def save_jobs(
    session: Session,
    run: ScrapeRun,
    source: ScrapeSource,
    jobs: list[dict[str, Any]],
    module: ModuleType | None = None,
    seen_offers: set[OfferKey] | None = None,
) -> tuple[list[PendingJobParseRun], int]:
    """Insert listings of ``source`` not yet in the DB (fetching their page HTML) and return
    ``(pending parse runs for the inserted jobs, duplicates)``. Each inserted job
    references ``run`` and ``source`` and gets a ``NOT_STARTED`` ``PendingJobParseRun``.
    A listing is a duplicate when its link is already known, or when it is the same offer
    (``offer_key``: link domain + title + company parsed with ``module``) as a job saved
    earlier in this run; ``seen_offers`` carries those keys across sources. Some sources
    publish one offer once per location, with only the URL differing. Offers are only
    compared within the current batch: the database is never scanned for them, since a
    company may legitimately post a similar role again later."""
    if seen_offers is None:
        seen_offers = set()
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
        key = offer_key(module, link, html)
        if key is not None:
            if key in seen_offers:
                log.info("Skipping duplicate offer %r: %s", key, link)
                duplicates += 1
                continue
            seen_offers.add(key)
        new_job = Job(
            link=link,
            source=source,
            html=html or None,
            scrape_run=run,
        )
        session.add(new_job)
        pending.append(PendingJobParseRun(job=new_job))
    session.add_all(pending)
    return pending, duplicates


def enqueue_parse_jobs(
    session: Session, pending: list[PendingJobParseRun], queue: Queue | None = None
) -> list[str]:
    """Enqueue ``parse_job`` for every pending row (which must be committed already) and
    store the RQ job ids on the rows. Returns the RQ job ids."""
    if not pending:
        return []
    # Imported here, not at module level: ``app.tasks.parse.parse`` imports the sources
    # package, whose parent package imports this module, so a top-level import would be
    # circular when the worker imports the parse task first (see test_rq_entrypoints).
    from app.tasks.parse import parse_job

    settings = get_settings()
    queue = queue or get_queue()
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
    """Scrape one source (``source``, its module name) or every enabled source (``None``).

    Returns::

        {
            "scrape_run_id": <id of the ScrapeRun row>,
            "sources": [{"source", "ok", "error", "jobs", "new", "duplicates"}, ...],
            "failed": ["<source name>", ...],
            "jobs": [{"link", "source"}, ...],
            "count": <number of scraped jobs>,
            "new": <jobs inserted into the DB>,
            "duplicates": <jobs already in the DB>,
            "parse_jobs": [<RQ job id of each enqueued parse task>, ...],
        }

    Raises ``ValueError`` when ``source`` is unknown or its module is broken.
    """
    init_db()
    with session_factory()() as session:
        rows = _resolve_sources(session, source)
        limited_to = rows[0] if source is not None else None
        run = ScrapeRun(source=limited_to, rq_job_id=_current_rq_job_id())
        session.add(run)
        session.commit()

        results: list[dict[str, Any]] = []
        jobs: list[dict[str, Any]] = []
        pending: list[PendingJobParseRun] = []
        duplicates = 0
        seen_offers: set[OfferKey] = set()
        try:
            for row in rows:
                result = run_source(row.key)
                module = result.pop("module", None)
                tagged = [{**job, "source": row.key} for job in result["jobs"]]
                row_pending, row_duplicates = save_jobs(
                    session, run, row, tagged, module, seen_offers
                )
                result["new"] = len(row_pending)
                result["duplicates"] = row_duplicates
                apply_run_result(
                    row,
                    ok=result["ok"],
                    error=result["error"],
                    scraped=len(tagged),
                    new=len(row_pending),
                )
                results.append(result)
                jobs.extend(tagged)
                pending.extend(row_pending)
                duplicates += row_duplicates
                session.commit()  # per-source durability on long runs

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
