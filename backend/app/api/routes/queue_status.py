"""``GET /api/queue``: what the background worker is doing right now.

Returns the job currently being processed (from RQ's started-job registry) and the jobs
still waiting in the queue, in the order the worker will pick them up. Meant for cheap
polling by the UI, so only lightweight job metadata is returned (no results / HTML).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from rq import Queue
from rq.job import Job
from rq.registry import StartedJobRegistry

from app.queue import get_queue

router = APIRouter()


class QueueJob(BaseModel):
    job_id: str
    kind: str
    """Short task name, e.g. ``scrape``, ``parse_job``, ``compile_latex``."""
    description: str
    status: str
    enqueued_at: str | None = None
    started_at: str | None = None
    meta: dict[str, Any] = {}


class QueueStatus(BaseModel):
    current: QueueJob | None
    pending: list[QueueJob]
    pending_count: int


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _kind(job: Job) -> str:
    # ``func_name`` is the dotted path (``app.tasks.scrape.scrape.scrape``); keep the leaf.
    return (job.func_name or "job").rsplit(".", 1)[-1]


def _to_out(job: Job) -> QueueJob:
    kind = _kind(job)
    description = job.description or kind
    # RQ's default description is the full call repr (``app.tasks...scrape('all')``);
    # replace that with something readable.
    if description.startswith("app."):
        args = ", ".join(repr(a) for a in job.args) if job.args else ""
        description = f"{kind}({args})"
    return QueueJob(
        job_id=job.id,
        kind=kind,
        description=description,
        status=job.get_status(refresh=False) or "unknown",
        enqueued_at=_iso(job.enqueued_at),
        started_at=_iso(job.started_at),
        meta={k: v for k, v in (job.meta or {}).items() if isinstance(v, (str, int, float, bool))},
    )


@router.get("", response_model=QueueStatus)
def queue_status(queue: Annotated[Queue, Depends(get_queue)], limit: int = 50) -> QueueStatus:
    registry = StartedJobRegistry(queue=queue)
    started = Job.fetch_many(registry.get_job_ids(), connection=queue.connection)
    # A single worker processes one job at a time; anything else here is a stale entry
    # from a crashed worker, which the registry cleans up on its own.
    current = next((_to_out(j) for j in started if j is not None), None)

    pending_ids = queue.get_job_ids()
    pending = [
        _to_out(j)
        for j in Job.fetch_many(pending_ids[:limit], connection=queue.connection)
        if j is not None
    ]
    return QueueStatus(current=current, pending=pending, pending_count=len(pending_ids))
