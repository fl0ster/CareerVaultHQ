"""LaTeX -> PDF compilation as a background job.

Flow for the frontend:

1. ``POST /api/latex/compile`` with either a multipart ``file`` (the ``.tex``) or a
   ``path`` previously returned by ``POST /api/latex/files``.
   -> ``202`` with ``job_id``, ``status_url``, ``events_url`` and ``pdf_url``.
2. Poll ``GET /api/latex/jobs/{job_id}`` or subscribe to the Server-Sent Events stream at
   ``GET /api/latex/jobs/{job_id}/events`` until ``status`` is ``finished`` or ``failed``.
3. Download ``GET /api/latex/jobs/{job_id}/pdf``.

The web server only stores the file and enqueues the job; ``app.worker`` does the work.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job

from app.config import Settings, get_settings
from app.queue import get_queue
from app.tasks.latex import compile_latex

router = APIRouter()

JobStatus = Literal[
    "queued", "started", "deferred", "finished", "failed", "stopped", "scheduled", "canceled"
]
TERMINAL_STATUSES = {"finished", "failed", "stopped", "canceled"}

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


# --------------------------------------------------------------------------- models


class UploadedFile(BaseModel):
    path: str
    """Identifier to pass as ``path`` to ``POST /latex/compile`` (relative to the LaTeX root)."""
    filename: str
    size: int


class CompileAccepted(BaseModel):
    job_id: str
    status: JobStatus
    source: str
    status_url: str
    events_url: str
    pdf_url: str


class JobInfo(BaseModel):
    job_id: str
    status: JobStatus
    source: str | None = None
    enqueued_at: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    pdf_url: str | None = None
    """Set once the job has finished successfully."""
    error: str | None = None
    """Compiler output (tail of the .log) when the job failed."""


# --------------------------------------------------------------------------- helpers


def _latex_upload_root(settings: Settings) -> Path:
    root = settings.latex_upload_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root

def _latex_jobs_root(settings: Settings) -> Path:
    root = settings.latex_jobs_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root

def _safe_filename(name: str | None) -> str:
    name = Path(name or "document.tex").name
    name = _SAFE_NAME.sub("_", name).strip("._") or "document"
    if not name.lower().endswith(".tex"):
        name += ".tex"
    return name


def _resolve_source(path: str, root: Path) -> Path:
    """Map a client supplied ``path`` onto a file under the LaTeX root (no traversal)."""
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root) or candidate.suffix.lower() != ".tex":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid path")
    if not candidate.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no uploaded file at {path!r}")
    return candidate


async def _store_upload(upload: UploadFile, root: Path, max_bytes: int) -> Path:
    content = await upload.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "uploaded file is empty")
    if len(content) > max_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"file exceeds {max_bytes} bytes"
        )
    job_dir = root / uuid.uuid4().hex
    job_dir.mkdir()
    target = job_dir / _safe_filename(upload.filename)
    target.write_bytes(content)
    return target


def _fetch_job(job_id: str, queue: Queue) -> Job:
    try:
        return Job.fetch(job_id, connection=queue.connection)
    except NoSuchJobError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown job") from exc


def _job_error(job: Job) -> str | None:
    result = job.latest_result()
    return result.exc_string if result is not None else None


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _job_info(job: Job, request: Request) -> JobInfo:
    job_status = job.get_status(refresh=False)
    info = JobInfo(
        job_id=job.id,
        status=job_status,
        source=job.meta.get("source"),
        enqueued_at=_iso(job.enqueued_at),
        started_at=_iso(job.started_at),
        ended_at=_iso(job.ended_at),
    )
    if job_status == "finished":
        info.pdf_url = str(request.url_for("latex_job_pdf", job_id=job.id))
    elif job_status == "failed":
        info.error = _job_error(job)
    return info


# --------------------------------------------------------------------------- routes


@router.post("/compile", response_model=CompileAccepted, status_code=status.HTTP_202_ACCEPTED)
async def compile_tex(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    queue: Annotated[Queue, Depends(get_queue)],
    file: Annotated[UploadFile | None, File(description="A .tex document to compile")] = None,
) -> CompileAccepted:
    """Queue a PDF build for an uploaded ``.tex`` file (either ``file`` or ``path``)."""
    if file is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "provide 'file'")

    root = _latex_upload_root(settings)
    source = (
        await _store_upload(file, root, settings.latex_max_upload_bytes)
        if file is not None
        else _resolve_source(path, root)  # type: ignore[arg-type]
    )
    relative = str(source.relative_to(root))
    out_dir = _latex_jobs_root(settings) / source.parent.name

    job = queue.enqueue(
        compile_latex,
        str(source),
        out_dir=str(out_dir),
        job_id=uuid.uuid4().hex,
        job_timeout=settings.latex_timeout + 30,
        result_ttl=settings.job_result_ttl,
        failure_ttl=settings.job_result_ttl,
        meta={"source": relative},
        description=f"pdflatex {relative}",
    )

    return CompileAccepted(
        job_id=job.id,
        status=job.get_status(refresh=False),
        source=relative,
        status_url=str(request.url_for("latex_job_status", job_id=job.id)),
        events_url=str(request.url_for("latex_job_events", job_id=job.id)),
        pdf_url=str(request.url_for("latex_job_pdf", job_id=job.id)),
    )


@router.get("/jobs/{job_id}", response_model=JobInfo, name="latex_job_status")
def job_status(
    job_id: str, request: Request, queue: Annotated[Queue, Depends(get_queue)]
) -> JobInfo:
    """Current state of a compile job. Poll until ``status`` is ``finished`` or ``failed``."""
    return _job_info(_fetch_job(job_id, queue), request)


@router.get("/jobs/{job_id}/events", name="latex_job_events")
async def job_events(
    job_id: str, request: Request, queue: Annotated[Queue, Depends(get_queue)]
) -> StreamingResponse:
    """Server-Sent Events: emits the job state on every change and closes when it is terminal.

    Frontend: ``new EventSource(events_url).onmessage = e => JSON.parse(e.data)``.
    """
    _fetch_job(job_id, queue)  # 404 early instead of inside the stream

    async def stream() -> AsyncIterator[str]:
        last: str | None = None
        while True:
            if await request.is_disconnected():
                return
            job = await asyncio.to_thread(_fetch_job, job_id, queue)
            info = _job_info(job, request)
            payload = info.model_dump_json()
            if payload != last:
                last = payload
                yield f"event: status\ndata: {payload}\n\n"
            if info.status in TERMINAL_STATUSES:
                return
            yield ": keep-alive\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/jobs/{job_id}/pdf", name="latex_job_pdf")
def job_pdf(
    job_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    queue: Annotated[Queue, Depends(get_queue)],
) -> FileResponse:
    """Download the generated PDF (``409`` while the job is still running)."""
    job = _fetch_job(job_id, queue)
    job_status = job.get_status(refresh=False)
    if job_status == "failed":
        raise HTTPException(status.HTTP_409_CONFLICT, _job_error(job) or "compilation failed")
    if job_status != "finished":
        raise HTTPException(status.HTTP_409_CONFLICT, f"job is {job_status}")

    result = job.return_value() or {}
    pdf = Path(result.get("pdf", "")).resolve()
    if not pdf.is_relative_to(_latex_jobs_root(settings)) or not pdf.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "pdf not found on disk")
    return FileResponse(pdf, media_type="application/pdf", filename=pdf.name)
