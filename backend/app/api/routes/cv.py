"""CVs generated for parsed jobs.

1. ``POST /api/cv/generate`` with ``{"job_id": <jobs.id>}`` -> ``202`` with the new
   ``generated_cvs`` row (status ``queued``); ``app.tasks.cv.generate_cv`` runs on the
   worker.
2. Poll ``GET /api/cv/{id}`` (or the list) until ``status`` is ``finished`` or ``failed``.
3. Download ``GET /api/cv/{id}/pdf`` (or the source at ``GET /api/cv/{id}/tex``).

``GET /api/cv`` lists every generated CV newest first with the job it was made for;
``?job_id=`` narrows it to one job. ``DELETE /api/cv/{id}`` removes the row and its files.
"""

from __future__ import annotations

import logging
import re
import shutil
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job as RqJob
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.config import Settings, get_settings
from app.db import get_session
from app.models import Application, CandidateDetails, Company, GeneratedCV, Job, JobParseResult, WorkHistoryEntry
from app.queue import get_queue
from app.services.applications import TAILOR_FAILED, TAILOR_QUEUED, store_tailored
from app.tasks.cv import generate_cv
from app.tasks.cv.generate import TAILOR_TIMEOUT, CvGenerationError, check_details, cv_dir, tailor_moved_role

log = logging.getLogger(__name__)

router = APIRouter()

MAX_PAGE_SIZE = 200

CvStatus = Literal["queued", "running", "finished", "failed"]

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


# --------------------------------------------------------------------------- models


class GenerateCvRequest(BaseModel):
    job_id: int
    """``jobs.id`` of a parsed job."""


class CvJobOut(BaseModel):
    id: int
    """``jobs.id``"""
    title: str | None
    company: str | None
    link: str
    source: str


RolePlacement = Literal["main", "early", "drop"]
"""Where the user put a role: listed in full, condensed into the early-career block, or left out."""


class TailoredRole(BaseModel):
    """What the pipeline's tailoring step made of a role for one placement (run on the
    worker: ``status`` says how far it got)."""

    status: Literal["queued", "done", "failed"] = "done"
    error: str | None = None
    """Why it failed."""
    rq_job_id: str | None = None
    context: str | None = None
    """Set once ``done``."""
    tech: list[str] | None = None
    """``main`` only."""
    original_context: str | None = None
    """The work history's description it was made from."""
    original_tech: list[str] = []
    """The work history's technologies it was made from."""
    cost: float = 0.0
    """USD its OpenRouter calls cost."""
    calls: int = 0
    """Number of OpenRouter calls it made."""


class CvOverrides(BaseModel):
    """The user's edits to how one application's CV is generated (see ``Application.cv_overrides``)."""

    headline_role: str | None = Field(default=None, max_length=256)
    """Used as the headline as is, instead of the one the LLM picks."""
    summary: str | None = Field(default=None, max_length=2000)
    """Used as the summary as is, instead of the generated one."""
    roles: dict[int, RolePlacement] = {}
    """``work_history.id`` -> placement, overriding the timeline rules for that role."""
    contexts: dict[int, Annotated[str, Field(max_length=2000)]] = {}
    """``work_history.id`` -> the role's description in the CV, used as is (listed or condensed)."""
    techs: dict[int, Annotated[list[Annotated[str, Field(max_length=128)]], Field(max_length=100)]] = {}
    """``work_history.id`` -> the technologies a listed role shows, in order, used as is."""
    tailored: dict[int, dict[Literal["main", "early"], TailoredRole]] = {}
    """``work_history.id`` -> placement -> the tailoring made when the user moved the role
    there (``POST /api/applications/{id}/cv/tailor``); the next CV prints it unless the user
    wrote their own. Kept by the server: not an edit, and ignored when sent."""

    def stored(self) -> dict | None:
        """The user's edits as kept on the row (``tailored`` left out: the server keeps it):
        blank fields left out, ``None`` when nothing is left."""
        data: dict[str, Any] = {}
        for key in ("headline_role", "summary"):
            value = (getattr(self, key) or "").strip()
            if value:
                data[key] = value
        if self.roles:
            data["roles"] = {str(k): v for k, v in sorted(self.roles.items())}
        contexts = {str(k): v.strip() for k, v in sorted(self.contexts.items()) if v.strip()}
        if contexts:
            data["contexts"] = contexts
        techs = {str(k): list(dict.fromkeys(t.strip() for t in v if t.strip())) for k, v in sorted(self.techs.items())}
        if techs:
            data["techs"] = techs  # an empty list is kept: the user removed every technology
        return data or None


class GeneratedCvOut(BaseModel):
    id: int
    status: CvStatus
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    headline_role: str | None
    core_technologies: list[str]
    summary: str | None
    warnings: list[str]
    """Pipeline steps that fell back to the original text (see ``app.tasks.cv``)."""
    cost: float | None
    """USD spent on OpenRouter calls for this CV (``None`` until it is finished)."""
    openrouter_calls: int | None
    job: CvJobOut
    pdf_url: str | None
    """Set once the CV is ``finished``."""
    tex_url: str | None
    overrides: CvOverrides | None = None
    """The user's edits the CV was generated with (``None``: none)."""


class GeneratedCvPage(BaseModel):
    items: list[GeneratedCvOut]
    total: int
    offset: int
    limit: int
    has_more: bool


# --------------------------------------------------------------------------- helpers


def _query():
    return (
        select(GeneratedCV)
        .join(JobParseResult, JobParseResult.id == GeneratedCV.job_parse_result_id)
        .join(Job, Job.id == JobParseResult.job_id)
        .options(
            joinedload(GeneratedCV.job_parse_result).joinedload(JobParseResult.job),
            joinedload(GeneratedCV.job_parse_result).joinedload(JobParseResult.company),
        )
    )


def _get_or_404(session: Session, cv_id: int) -> GeneratedCV:
    cv = session.scalar(_query().where(GeneratedCV.id == cv_id))
    if cv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown generated cv")
    return cv


def reconcile_cv(session: Session, queue: Queue, cv: GeneratedCV) -> None:
    """A generation the worker lost (killed by the RQ timeout, worker crashed) stays
    ``running`` in the database; pick the failure up from RQ when it is visible there."""
    if cv.status not in (GeneratedCV.STATUS_QUEUED, GeneratedCV.STATUS_RUNNING) or not cv.rq_job_id:
        return
    try:
        rq_job = RqJob.fetch(cv.rq_job_id, connection=queue.connection)
    except NoSuchJobError:
        return
    except Exception:  # Redis unreachable: show what the database knows
        log.debug("Could not fetch RQ job %s", cv.rq_job_id, exc_info=True)
        return
    if rq_job.get_status(refresh=False) == "failed":
        latest = rq_job.latest_result()
        cv.status = GeneratedCV.STATUS_FAILED
        cv.error = (latest.exc_string if latest is not None else None) or "worker failed"
        cv.finished_at = rq_job.ended_at or datetime.now(tz=cv.created_at.tzinfo)
        session.commit()


def cv_out(cv: GeneratedCV, request: Request) -> GeneratedCvOut:
    parsed = cv.job_parse_result
    job = parsed.job
    finished = cv.status == GeneratedCV.STATUS_FINISHED
    return GeneratedCvOut(
        id=cv.id,
        status=cv.status,  # type: ignore[arg-type]
        error=cv.error,
        created_at=cv.created_at,
        started_at=cv.started_at,
        finished_at=cv.finished_at,
        headline_role=cv.headline_role,
        core_technologies=list(cv.core_technologies or []),
        summary=cv.summary,
        warnings=list((cv.pipeline or {}).get("warnings") or []),
        cost=(cv.pipeline or {}).get("cost"),
        openrouter_calls=(cv.pipeline or {}).get("openrouter_calls"),
        job=CvJobOut(
            id=job.id,
            title=parsed.title,
            company=parsed.company.name if parsed.company is not None else None,
            link=job.link,
            source=job.source.key,
        ),
        pdf_url=str(request.url_for("generated_cv_pdf", cv_id=cv.id)) if finished else None,
        tex_url=str(request.url_for("generated_cv_tex", cv_id=cv.id)) if finished else None,
        overrides=CvOverrides.model_validate(cv.overrides) if cv.overrides else None,
    )


def _download_name(session: Session, cv: GeneratedCV, suffix: str) -> str:
    """``First_Last_CV_Company.pdf``-style file name for the download."""
    details = session.scalar(select(CandidateDetails).order_by(CandidateDetails.id.desc()))
    parts = []
    if details is not None:
        parts += [details.first_name, details.last_name]
    parts.append("CV")
    company = cv.job_parse_result.company
    if company is not None:
        parts.append(company.name)
    name = "_".join(_SAFE_NAME.sub("_", p).strip("_") for p in parts if p and p.strip())
    return f"{name or 'CV'}{suffix}"


def _file_or_409(settings: Settings, cv: GeneratedCV, path: str | None) -> Path:
    if cv.status == GeneratedCV.STATUS_FAILED:
        raise HTTPException(status.HTTP_409_CONFLICT, cv.error or "generation failed")
    if cv.status != GeneratedCV.STATUS_FINISHED or not path:
        raise HTTPException(status.HTTP_409_CONFLICT, f"generation is {cv.status}")
    file = Path(path).resolve()
    if not file.is_relative_to(settings.cv_root.resolve()) or not file.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file not found on disk")
    return file


def check_cv_inputs(session: Session) -> None:
    """``400`` unless the inputs every CV needs (work history with a position that has
    started, candidate name) exist."""
    started = (
        select(func.count())
        .select_from(WorkHistoryEntry)
        .where(WorkHistoryEntry.kind == WorkHistoryEntry.KIND_JOB, WorkHistoryEntry.date_start <= date.today())
    )
    if session.scalar(started) == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "missing work history: add at least one position first")
    details = session.scalar(select(CandidateDetails).order_by(CandidateDetails.id.desc()))
    try:
        check_details(details)
    except CvGenerationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


def enqueue_tailoring(
    session: Session, queue: Queue, settings: Settings, application: Application, role_id: int, placement: str
) -> None:
    """Mark the tailoring of a moved role ``queued`` on the application and queue
    ``tailor_moved_role`` for it; when the queue is unreachable it is marked ``failed``
    instead of raising. Commits."""
    rq_job_id = uuid.uuid4().hex
    store_tailored(application, role_id, placement, {"status": TAILOR_QUEUED, "rq_job_id": rq_job_id})
    session.commit()
    try:
        queue.enqueue(
            tailor_moved_role,
            application.id,
            role_id,
            placement,
            job_id=rq_job_id,
            job_timeout=TAILOR_TIMEOUT,
            result_ttl=settings.job_result_ttl,
            failure_ttl=settings.job_result_ttl,
            meta={"application_id": application.id, "work_history_id": role_id},
            description=f"tailor position {role_id} ({placement}) for application {application.id}",
        )
    except Exception as exc:
        log.exception("Could not enqueue tailoring position %d for application %d", role_id, application.id)
        store_tailored(application, role_id, placement, {"status": TAILOR_FAILED, "error": f"could not enqueue it: {exc}"})
        session.commit()


def reconcile_tailoring(session: Session, queue: Queue, application: Application) -> None:
    """A tailoring the worker lost (killed by the RQ timeout, worker crashed) stays ``queued``
    in the database; pick the failure up from RQ when it is visible there (see ``reconcile_cv``)."""
    for role_id, by_placement in ((application.cv_overrides or {}).get("tailored") or {}).items():
        for placement, made in (by_placement or {}).items():
            if (made or {}).get("status") != TAILOR_QUEUED or not made.get("rq_job_id"):
                continue
            try:
                rq_job = RqJob.fetch(made["rq_job_id"], connection=queue.connection)
            except NoSuchJobError:
                continue
            except Exception:  # Redis unreachable: show what the database knows
                log.debug("Could not fetch RQ job %s", made["rq_job_id"], exc_info=True)
                return
            if rq_job.get_status(refresh=False) == "failed":
                latest = rq_job.latest_result()
                trace = (latest.exc_string if latest is not None else None) or ""
                error = (trace.strip().splitlines() or ["worker failed"])[-1]  # the exception, not the traceback
                store_tailored(application, int(role_id), placement, {"status": TAILOR_FAILED, "error": error})
                session.commit()


def enqueue_cv(
    session: Session, queue: Queue, settings: Settings, parsed: JobParseResult, overrides: dict | None = None
) -> GeneratedCV:
    """Create a ``generated_cvs`` row for ``parsed`` (generated with the user's ``overrides``,
    see ``CvOverrides``) and queue its generation. When the queue is unreachable the row is
    committed as ``failed`` instead of raising."""
    cv = GeneratedCV(job_parse_result_id=parsed.id, rq_job_id=uuid.uuid4().hex, overrides=overrides or None)
    session.add(cv)
    session.commit()
    session.refresh(cv)
    try:
        queue.enqueue(
            generate_cv,
            cv.id,
            job_id=cv.rq_job_id,
            job_timeout=settings.cv_timeout,
            result_ttl=settings.job_result_ttl,
            failure_ttl=settings.job_result_ttl,
            meta={"generated_cv_id": cv.id, "job_id": parsed.job_id},
            description=f"generate cv {cv.id} for job {parsed.job_id}",
        )
    except Exception as exc:
        log.exception("Could not enqueue CV generation %d", cv.id)
        cv.status = GeneratedCV.STATUS_FAILED
        cv.error = f"could not enqueue the generation: {exc}"
        session.commit()
    return cv


# --------------------------------------------------------------------------- routes


@router.post("/generate", response_model=GeneratedCvOut, status_code=status.HTTP_202_ACCEPTED)
def generate(
    payload: GenerateCvRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    queue: Annotated[Queue, Depends(get_queue)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> GeneratedCvOut:
    """Queue a CV generation for a parsed job.

    ``404`` when the job is unknown or not parsed yet; ``400`` when there is no work
    history or the candidate's name is not set; ``503`` when the queue is unreachable.
    """
    parsed = session.scalar(
        select(JobParseResult)
        .where(JobParseResult.job_id == payload.job_id)
        .options(joinedload(JobParseResult.job), joinedload(JobParseResult.company))
    )
    if parsed is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown or unparsed job")
    check_cv_inputs(session)
    cv = enqueue_cv(session, queue, settings, parsed)
    if cv.status == GeneratedCV.STATUS_FAILED:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "job queue unavailable; try again later")
    return cv_out(_get_or_404(session, cv.id), request)


@router.get("", response_model=GeneratedCvPage)
def list_cvs(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    queue: Annotated[Queue, Depends(get_queue)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
    job_id: int | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> GeneratedCvPage:
    """Generated CVs, newest first, each with the job it was generated for;
    ``q`` keeps those whose job title or company name contains it (case-insensitive)."""
    query = _query()
    if job_id is not None:
        query = query.where(Job.id == job_id)
    needle = (q or "").strip().lower()
    if needle:
        query = query.outerjoin(Company, Company.id == JobParseResult.company_id).where(
            or_(
                func.lower(JobParseResult.title).contains(needle, autoescape=True),
                func.lower(Company.name).contains(needle, autoescape=True),
            )
        )
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    cvs = session.scalars(query.order_by(GeneratedCV.id.desc()).offset(offset).limit(limit)).all()
    for cv in cvs:
        reconcile_cv(session, queue, cv)
    return GeneratedCvPage(
        items=[cv_out(cv, request) for cv in cvs],
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + len(cvs) < total,
    )


@router.get("/{cv_id}", response_model=GeneratedCvOut)
def get_cv(
    cv_id: int,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    queue: Annotated[Queue, Depends(get_queue)],
) -> GeneratedCvOut:
    """One generated CV; poll until ``status`` is ``finished`` or ``failed``."""
    cv = _get_or_404(session, cv_id)
    reconcile_cv(session, queue, cv)
    return cv_out(cv, request)


@router.get("/{cv_id}/pdf", name="generated_cv_pdf")
def get_pdf(
    cv_id: int,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> FileResponse:
    """Download the PDF (``409`` while the generation is still running or has failed)."""
    cv = _get_or_404(session, cv_id)
    pdf = _file_or_409(settings, cv, cv.pdf_path)
    return FileResponse(pdf, media_type="application/pdf", filename=_download_name(session, cv, ".pdf"))


@router.get("/{cv_id}/tex", name="generated_cv_tex")
def get_tex(
    cv_id: int,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> FileResponse:
    """Download the LaTeX source the PDF was built from."""
    cv = _get_or_404(session, cv_id)
    tex = _file_or_409(settings, cv, cv.tex_path)
    return FileResponse(tex, media_type="application/x-tex", filename=_download_name(session, cv, ".tex"))


@router.get("/{cv_id}/pipeline", response_model=dict[str, Any])
def get_pipeline(cv_id: int, session: Annotated[Session, Depends(get_session)]) -> dict[str, Any]:
    """What the pipeline did (relevance per role, tailored entries, timeline log, warnings)."""
    return _get_or_404(session, cv_id).pipeline or {}


@router.delete("/{cv_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cv(
    cv_id: int,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """Delete the generated CV and its files (``409`` while it is still being generated)."""
    cv = _get_or_404(session, cv_id)
    if cv.status in (GeneratedCV.STATUS_QUEUED, GeneratedCV.STATUS_RUNNING):
        raise HTTPException(status.HTTP_409_CONFLICT, f"generation is {cv.status}")
    folder = cv_dir(settings, cv.id)
    if folder.is_dir() and folder.is_relative_to(settings.cv_root.resolve()):
        shutil.rmtree(folder, ignore_errors=True)
    session.delete(cv)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
