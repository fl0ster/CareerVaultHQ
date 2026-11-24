"""Import personal details and work history from a CV PDF (a preview; nothing is saved).

1. ``POST /api/cv-import`` with a multipart ``file`` (a text-based PDF) -> ``202`` with
   the RQ ``job_id``; ``app.tasks.cv_import.import_cv`` runs on the worker.
2. Poll ``GET /api/cv-import/jobs/{job_id}`` until ``status`` is ``finished`` (``result``
   is set) or ``failed`` (``error`` says why, e.g. a scanned PDF without text).
3. Let the user review ``result`` and save it with ``PUT /api/candidate-details``
   (``result.candidate_details``) and ``POST /api/work-history/json``
   (``result.work_history``); both accept it as-is. ``result.warnings`` lists what was
   dropped or assumed.

The uploaded PDF is deleted by the worker once parsed; the result stays in Redis for
``job_result_ttl`` seconds.
"""

from __future__ import annotations

import contextlib
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job

from app.config import Settings, get_settings
from app.queue import get_queue
from app.tasks.cv_import import CvImportResult, import_cv, import_timeout

log = logging.getLogger(__name__)

router = APIRouter()

JOB_KIND = "cv_import"
"""``job.meta["kind"]``: the status endpoint only serves jobs enqueued here."""

PDF_MAGIC = b"%PDF-"
MAGIC_WINDOW = 1024
"""PDF readers accept the header anywhere in the first kilobyte."""

JobStatus = Literal["queued", "started", "deferred", "finished", "stopped", "scheduled", "canceled", "failed"]


class CvImportAccepted(BaseModel):
    job_id: str
    status: JobStatus
    status_url: str


class CvImportJob(BaseModel):
    job_id: str
    status: JobStatus
    filename: str | None
    enqueued_at: datetime | None
    started_at: datetime | None
    ended_at: datetime | None
    error: str | None
    """Why the import failed (``status == "failed"``)."""
    result: CvImportResult | None
    """The parsed CV (``status == "finished"``)."""


def _store(data: bytes, root: Path) -> Path:
    target = root / uuid.uuid4().hex / "cv.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def _error_message(job: Job) -> str | None:
    """Last line of the traceback without the exception's module path."""
    result = job.latest_result()
    if result is None or not result.exc_string:
        return None
    last = result.exc_string.strip().splitlines()[-1]
    return re.sub(r"^[A-Za-z_][\w.]*: ", "", last) or last


@router.post("", response_model=CvImportAccepted, status_code=status.HTTP_202_ACCEPTED)
def start_import(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    queue: Annotated[Queue, Depends(get_queue)],
    file: Annotated[UploadFile, File(description="The CV as a text-based PDF")],
) -> CvImportAccepted:
    """Queue the parsing of an uploaded CV PDF: ``400`` when empty, ``413`` when larger than
    ``cv_import_max_upload_bytes``, ``415`` when not a PDF, ``503`` when the queue is down."""
    limit = settings.cv_import_max_upload_bytes
    data = file.file.read(limit + 1)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "the uploaded file is empty")
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"the file is larger than {limit} bytes")
    if PDF_MAGIC not in data[:MAGIC_WINDOW]:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "the file is not a PDF")

    path = _store(data, settings.cv_import_upload_root)
    try:
        job = queue.enqueue(
            import_cv,
            str(path),
            job_id=uuid.uuid4().hex,
            job_timeout=import_timeout(settings),
            result_ttl=settings.job_result_ttl,
            failure_ttl=settings.job_result_ttl,
            meta={"kind": JOB_KIND, "filename": (file.filename or "")[:256] or None},
            description="import CV",
        )
    except Exception as exc:
        log.exception("Could not enqueue the CV import")
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)
            path.parent.rmdir()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "the job queue is unavailable") from exc

    return CvImportAccepted(
        job_id=job.id,
        status=job.get_status(refresh=False),
        status_url=str(request.url_for("cv_import_job_status", job_id=job.id)),
    )


@router.get("/jobs/{job_id}", response_model=CvImportJob, name="cv_import_job_status")
def job_status(job_id: str, queue: Annotated[Queue, Depends(get_queue)]) -> CvImportJob:
    """State of an import; ``result`` once finished, ``error`` once failed."""
    try:
        job = Job.fetch(job_id, connection=queue.connection)
    except NoSuchJobError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown job") from exc
    if job.meta.get("kind") != JOB_KIND:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown job")

    job_state = job.get_status(refresh=False)
    result = None
    error = None
    if job_state == "finished":
        value = job.return_value()
        result = CvImportResult.model_validate(value) if value is not None else None
    elif job_state == "failed":
        error = _error_message(job) or "the import failed"
    return CvImportJob(
        job_id=job.id,
        status=job_state,
        filename=job.meta.get("filename"),
        enqueued_at=job.enqueued_at,
        started_at=job.started_at,
        ended_at=job.ended_at,
        error=error,
        result=result,
    )
