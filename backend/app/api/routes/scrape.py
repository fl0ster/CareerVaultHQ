"""Job scraping as a background job.

1. ``POST /api/scrape`` (optional JSON body ``{"source": "skillshot"}``; omit to run all)
   -> ``202`` with ``job_id`` and ``status_url``.
2. Poll ``GET /api/scrape/jobs/{job_id}`` until ``status`` is ``finished`` or ``failed``.
   On success ``result`` holds the scraped jobs and ``count`` the number of them.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job

from app.config import Settings, get_settings
from app.queue import get_scrapper_queue
from app.tasks.scrape import scrape
from app.tasks.scrape.sources import get_available_sources

router = APIRouter()

JobStatus = Literal[
    "queued", "started", "deferred", "finished", "failed", "stopped", "scheduled", "canceled"
]

SCRAPE_TIMEOUT = 600


class ScrapeRequest(BaseModel):
    source: str | None = None
    """Scraper source name (see ``GET /scrape/sources``). ``None`` runs every source."""


class ScrapeAccepted(BaseModel):
    job_id: str
    status: JobStatus
    source: str | None
    status_url: str


class ScrapeJobInfo(BaseModel):
    job_id: str
    status: JobStatus
    source: str | None = None
    enqueued_at: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    count: int | None = None
    """Number of scraped jobs (set once the job has finished)."""
    result: dict[str, Any] | None = None
    """Full scrape result (set once the job has finished)."""
    error: str | None = None


def _fetch_job(job_id: str, queue: Queue) -> Job:
    try:
        return Job.fetch(job_id, connection=queue.connection)
    except NoSuchJobError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown job") from exc


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _job_info(job: Job) -> ScrapeJobInfo:
    job_status = job.get_status(refresh=False)
    info = ScrapeJobInfo(
        job_id=job.id,
        status=job_status,
        source=job.meta.get("source"),
        enqueued_at=_iso(job.enqueued_at),
        started_at=_iso(job.started_at),
        ended_at=_iso(job.ended_at),
    )
    if job_status == "finished":
        result = job.return_value() or {}
        info.result = result
        info.count = result.get("count", 0)
    elif job_status == "failed":
        latest = job.latest_result()
        info.error = latest.exc_string if latest is not None else None
    return info


@router.get("/sources", response_model=list[str])
def list_sources() -> list[str]:
    """Names of the available scraper sources."""
    return get_available_sources()


@router.post("", response_model=ScrapeAccepted, status_code=status.HTTP_202_ACCEPTED)
def start_scrape(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    queue: Annotated[Queue, Depends(get_scrapper_queue)],
    body: ScrapeRequest | None = None,
) -> ScrapeAccepted:
    """Queue a scrape of one source (or all sources when ``source`` is omitted)."""
    source = body.source if body else None
    available = get_available_sources()
    if source is not None and source not in available:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"unknown source {source!r}; available: {', '.join(available)}",
        )

    job = queue.enqueue(
        scrape,
        source,
        job_id=uuid.uuid4().hex,
        job_timeout=SCRAPE_TIMEOUT,
        result_ttl=settings.job_result_ttl,
        failure_ttl=settings.job_result_ttl,
        meta={"source": source},
        description=f"scrape {source or 'all'}",
    )
    return ScrapeAccepted(
        job_id=job.id,
        status=job.get_status(refresh=False),
        source=source,
        status_url=str(request.url_for("scrape_job_status", job_id=job.id)),
    )


@router.get("/jobs/{job_id}", response_model=ScrapeJobInfo, name="scrape_job_status")
def job_status(
    job_id: str, queue: Annotated[Queue, Depends(get_scrapper_queue)]
) -> ScrapeJobInfo:
    """Current state of a scrape job; includes ``result`` and ``count`` once finished."""
    return _job_info(_fetch_job(job_id, queue))
