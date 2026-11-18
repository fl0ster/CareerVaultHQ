"""Job applications made for evaluated jobs.

* ``POST /api/applications`` with ``{"job_evaluation_id": ...}`` creates the application
  (``409`` when the job already has one), records its initial state (``SHORTLISTED`` unless
  ``status`` says otherwise, ``null`` for none) and queues a tailored CV for the job.
* ``GET /api/applications`` lists them newest first (``?status=INTERVIEW`` filters by
  current state, ``?q=acme`` by job title or company name); ``GET``/``PATCH``/``DELETE /api/applications/{id}`` work on one.
* ``POST /api/applications/{id}/events`` records a state change with its own note;
  ``PATCH``/``DELETE /api/applications/{id}/events/{event_id}`` edit or remove one.
  ``SHORTLISTED`` is only recorded at creation: it cannot be added, removed or switched
  to/from later (``422``), though its note and date can be edited. No state can be added
  while the current one is ``OFFER`` or ``REJECTED`` (``409``) until that state is removed.
  ``APPLIED`` can be recorded once, only while the current state is ``SHORTLISTED`` (``409``).
* ``POST /api/applications/{id}/cv`` generates the CV again.
* ``GET /api/applications/statuses`` lists the available states;
  ``POST /api/applications/statuses`` adds a custom one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from rq import Queue
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.api.routes.cv import (
    GeneratedCvOut,
    check_cv_inputs,
    cv_out,
    enqueue_cv,
    reconcile_cv,
)
from app.config import Settings, get_settings
from app.db import get_session
from app.models import (
    Application,
    ApplicationEvent,
    ApplicationStatus,
    GeneratedCV,
    Job,
    JobDecision,
    JobEvaluation,
    JobParseResult,
)
from app.queue import get_queue
from app.services.applications import ensure_statuses, set_job_decision
from app.services.relevance import relevance

router = APIRouter()

MAX_PAGE_SIZE = 200
DEFAULT_STATUS = "SHORTLISTED"
INITIAL_ONLY_STATUS = "SHORTLISTED"
"""Recorded only when the application is created: it cannot be added, removed or
switched to/from afterwards (its note and date can still be edited)."""
APPLIED_STATUS = "APPLIED"
"""Recorded at most once, and only straight after ``SHORTLISTED`` (its current state)."""
FINAL_STATUSES = frozenset({"OFFER", "REJECTED"})
"""Terminal states: once one is current, no further state can be added (removing it reopens the
application)."""


# --------------------------------------------------------------------------- models


class StatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    label: str
    position: int
    next_key: str | None = None
    """Default next state (``key``), if any."""


class StatusCreate(BaseModel):
    key: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    label: str | None = Field(default=None, max_length=128)
    position: int | None = None

    @field_validator("key")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()


class EventOut(BaseModel):
    id: int
    status: StatusOut
    note: str
    occurred_at: datetime
    created_at: datetime


class ApplicationJobOut(BaseModel):
    id: int
    """``jobs.id``"""
    title: str | None
    company: str | None
    company_id: int | None = None
    """``companies.id`` of the hiring company, when it was resolved."""
    company_notes: str | None = None
    """The company's own notes (shared by every application to it); ``None`` without a company."""
    company_tag: str | None = None
    """The company's tag (``Company.TAGS``), if any."""
    link: str
    source: str


class ApplicationEvaluationOut(BaseModel):
    id: int
    candidate_profile_id: int
    relevance: float
    """``match_probability`` on the [-1, 1] display scale (see ``relevance``)."""


class ApplicationOut(BaseModel):
    id: int
    notes: str
    created_at: datetime
    updated_at: datetime
    status: StatusOut | None
    """Current state (that of the latest event); ``None`` when no state was recorded."""
    events: list[EventOut]
    """State history, oldest first."""
    job: ApplicationJobOut
    evaluation: ApplicationEvaluationOut | None
    cv: GeneratedCvOut | None


class ApplicationPage(BaseModel):
    items: list[ApplicationOut]
    total: int
    offset: int
    limit: int
    has_more: bool


class ApplicationCreate(BaseModel):
    job_evaluation_id: int
    status: str | None = DEFAULT_STATUS
    """Initial state key; ``null`` records no state."""
    status_note: str = ""
    notes: str = ""


class ApplicationUpdate(BaseModel):
    notes: str


def _to_utc(value: datetime | None) -> datetime | None:
    """SQLite drops the offset, so every stored timestamp is UTC; naive input is UTC."""
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class EventCreate(BaseModel):
    status: str
    note: str = ""
    occurred_at: datetime | None = None

    _utc = field_validator("occurred_at")(_to_utc)


class EventUpdate(BaseModel):
    status: str | None = None
    note: str | None = None
    occurred_at: datetime | None = None

    _utc = field_validator("occurred_at")(_to_utc)


# --------------------------------------------------------------------------- helpers


def _query():
    return select(Application).options(
        joinedload(Application.job_parse_result)
        .joinedload(JobParseResult.job)
        .joinedload(Job.source),
        joinedload(Application.job_parse_result).joinedload(JobParseResult.company),
        joinedload(Application.job_evaluation),
        joinedload(Application.generated_cv),
        selectinload(Application.events).joinedload(ApplicationEvent.status),
    )


def _get_or_404(session: Session, application_id: int) -> Application:
    application = session.scalar(_query().where(Application.id == application_id))
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown application")
    return application


def _status_or_422(session: Session, key: str) -> ApplicationStatus:
    ensure_statuses(session)
    row = session.scalar(select(ApplicationStatus).where(ApplicationStatus.key == key.upper()))
    if row is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown status {key!r}")
    return row


def _reject_initial_only(key: str) -> None:
    if key.upper() == INITIAL_ONLY_STATUS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{INITIAL_ONLY_STATUS} is only set when the application is created",
        )


def _cv_with_job(session: Session, cv_id: int) -> GeneratedCV:
    return session.scalar(
        select(GeneratedCV)
        .where(GeneratedCV.id == cv_id)
        .options(
            joinedload(GeneratedCV.job_parse_result)
            .joinedload(JobParseResult.job)
            .joinedload(Job.source),
            joinedload(GeneratedCV.job_parse_result).joinedload(JobParseResult.company),
        )
    )


def _to_out(
    application: Application, request: Request, session: Session, queue: Queue
) -> ApplicationOut:
    parsed = application.job_parse_result
    job = parsed.job
    evaluation = application.job_evaluation
    current = application.current_event
    cv = None
    if application.generated_cv_id is not None:
        cv_row = _cv_with_job(session, application.generated_cv_id)
        if cv_row is not None:
            reconcile_cv(session, queue, cv_row)
            cv = cv_out(cv_row, request)
    return ApplicationOut(
        id=application.id,
        notes=application.notes or "",
        created_at=application.created_at,
        updated_at=application.updated_at,
        status=StatusOut.model_validate(current.status) if current else None,
        events=[
            EventOut(
                id=e.id,
                status=StatusOut.model_validate(e.status),
                note=e.note or "",
                occurred_at=e.occurred_at,
                created_at=e.created_at,
            )
            for e in application.events
        ],
        job=ApplicationJobOut(
            id=job.id,
            title=parsed.title,
            company=parsed.company.name if parsed.company is not None else None,
            company_id=parsed.company.id if parsed.company is not None else None,
            company_notes=(parsed.company.notes or "") if parsed.company is not None else None,
            company_tag=parsed.company.tag if parsed.company is not None else None,
            link=job.link,
            source=job.source.key,
        ),
        evaluation=ApplicationEvaluationOut(
            id=evaluation.id,
            candidate_profile_id=evaluation.candidate_profile_id,
            relevance=relevance(evaluation.match_probability, get_settings().relevant_job_threshold),
        )
        if evaluation is not None
        else None,
        cv=cv,
    )


def _reload_out(
    session: Session, application_id: int, request: Request, queue: Queue
) -> ApplicationOut:
    session.expire_all()
    return _to_out(_get_or_404(session, application_id), request, session, queue)


# --------------------------------------------------------------------------- statuses


@router.get("/statuses", response_model=list[StatusOut])
def list_statuses(session: Annotated[Session, Depends(get_session)]) -> list[StatusOut]:
    """Available application states in display order."""
    ensure_statuses(session)
    rows = session.scalars(
        select(ApplicationStatus).order_by(ApplicationStatus.position, ApplicationStatus.id)
    ).all()
    return [StatusOut.model_validate(r) for r in rows]


@router.post("/statuses", response_model=StatusOut, status_code=status.HTTP_201_CREATED)
def create_status(
    payload: StatusCreate, session: Annotated[Session, Depends(get_session)]
) -> StatusOut:
    """Add a custom state (``409`` when the key exists). Listed last unless ``position``
    is given."""
    ensure_statuses(session)
    if session.scalar(select(ApplicationStatus).where(ApplicationStatus.key == payload.key)):
        raise HTTPException(status.HTTP_409_CONFLICT, "status already exists")
    position = payload.position
    if position is None:
        position = (session.scalar(select(func.max(ApplicationStatus.position))) or 0) + 10
    row = ApplicationStatus(
        key=payload.key,
        label=(payload.label or "").strip() or payload.key.replace("_", " ").title(),
        position=position,
    )
    session.add(row)
    session.commit()
    return StatusOut.model_validate(row)


# --------------------------------------------------------------------------- applications


@router.post("", response_model=ApplicationOut, status_code=status.HTTP_201_CREATED)
def create_application(
    payload: ApplicationCreate,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    queue: Annotated[Queue, Depends(get_queue)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ApplicationOut:
    """Create an application for an evaluated job and queue a CV for it.

    ``404`` for an unknown evaluation, ``409`` when the job already has an application,
    ``400`` when a CV cannot be generated (no work history / candidate name). When the
    queue is down the application is still created and its CV is reported ``failed``.
    """
    evaluation = session.get(JobEvaluation, payload.job_evaluation_id)
    if evaluation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown job evaluation")
    existing = session.scalar(
        select(Application.id).where(
            Application.job_parse_result_id == evaluation.job_parse_result_id
        )
    )
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"application #{existing} already exists for this job"
        )
    initial = _status_or_422(session, payload.status) if payload.status else None
    check_cv_inputs(session)

    application = Application(
        job_parse_result_id=evaluation.job_parse_result_id,
        job_evaluation_id=evaluation.id,
        notes=payload.notes,
    )
    if initial is not None:
        application.events.append(ApplicationEvent(status=initial, note=payload.status_note))
    session.add(application)
    set_job_decision(session, evaluation.job_parse_result_id, JobDecision.ACCEPTED)
    session.commit()

    cv = enqueue_cv(session, queue, settings, evaluation.job_parse_result)
    application.generated_cv_id = cv.id
    session.commit()
    return _reload_out(session, application.id, request, queue)


def _matches(application: Application, needle: str) -> bool:
    parsed = application.job_parse_result
    company = parsed.company.name if parsed.company is not None else None
    return any(needle in (text or "").casefold() for text in (parsed.title, company))


@router.get("", response_model=ApplicationPage)
def list_applications(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    queue: Annotated[Queue, Depends(get_queue)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
    status_key: Annotated[str | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> ApplicationPage:
    """Applications, newest first; ``status`` keeps those whose current state matches,
    ``q`` those whose job title or company name contains it (case-insensitive)."""
    applications = session.scalars(_query().order_by(Application.id.desc())).unique().all()
    if status_key:
        key = status_key.upper()
        applications = [
            a for a in applications if a.current_event and a.current_event.status.key == key
        ]
    needle = (q or "").strip().casefold()
    if needle:
        applications = [a for a in applications if _matches(a, needle)]
    page = applications[offset : offset + limit]
    return ApplicationPage(
        items=[_to_out(a, request, session, queue) for a in page],
        total=len(applications),
        offset=offset,
        limit=limit,
        has_more=offset + len(page) < len(applications),
    )


@router.get("/{application_id}", response_model=ApplicationOut)
def get_application(
    application_id: int,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    queue: Annotated[Queue, Depends(get_queue)],
) -> ApplicationOut:
    return _to_out(_get_or_404(session, application_id), request, session, queue)


@router.patch("/{application_id}", response_model=ApplicationOut)
def update_application(
    application_id: int,
    payload: ApplicationUpdate,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    queue: Annotated[Queue, Depends(get_queue)],
) -> ApplicationOut:
    """Replace the application's notes."""
    application = _get_or_404(session, application_id)
    application.notes = payload.notes
    session.commit()
    return _reload_out(session, application_id, request, queue)


@router.delete("/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_application(
    application_id: int, session: Annotated[Session, Depends(get_session)]
) -> Response:
    """Delete the application and its state history (the generated CV is kept)."""
    session.delete(_get_or_404(session, application_id))
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{application_id}/cv", response_model=ApplicationOut)
def regenerate_cv(
    application_id: int,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    queue: Annotated[Queue, Depends(get_queue)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ApplicationOut:
    """Queue a new CV for the application's job and attach it (``409`` while the current
    one is still being generated)."""
    application = _get_or_404(session, application_id)
    current = application.generated_cv
    if current is not None:
        reconcile_cv(session, queue, current)
        if current.status in (GeneratedCV.STATUS_QUEUED, GeneratedCV.STATUS_RUNNING):
            raise HTTPException(status.HTTP_409_CONFLICT, f"generation is {current.status}")
    check_cv_inputs(session)
    cv = enqueue_cv(session, queue, settings, application.job_parse_result)
    application.generated_cv_id = cv.id
    session.commit()
    return _reload_out(session, application_id, request, queue)


# --------------------------------------------------------------------------- events


def _event_or_404(application: Application, event_id: int) -> ApplicationEvent:
    for event in application.events:
        if event.id == event_id:
            return event
    raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown application event")


@router.post(
    "/{application_id}/events", response_model=ApplicationOut, status_code=status.HTTP_201_CREATED
)
def add_event(
    application_id: int,
    payload: EventCreate,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    queue: Annotated[Queue, Depends(get_queue)],
) -> ApplicationOut:
    """Record a state change; it becomes the current state unless ``occurred_at`` puts it
    before a later one."""
    _reject_initial_only(payload.status)
    application = _get_or_404(session, application_id)
    current = application.current_event
    if current is not None and current.status.key in FINAL_STATUSES:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"application is {current.status.key}; remove that state to record new ones",
        )
    if payload.status.upper() == APPLIED_STATUS:
        if any(e.status.key == APPLIED_STATUS for e in application.events):
            raise HTTPException(status.HTTP_409_CONFLICT, "application is already APPLIED")
        if current is None or current.status.key != INITIAL_ONLY_STATUS:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{APPLIED_STATUS} can only follow {INITIAL_ONLY_STATUS}",
            )
    event = ApplicationEvent(
        application_id=application.id,
        status=_status_or_422(session, payload.status),
        note=payload.note,
    )
    if payload.occurred_at is not None:
        event.occurred_at = payload.occurred_at
    session.add(event)
    session.commit()
    return _reload_out(session, application_id, request, queue)


@router.patch("/{application_id}/events/{event_id}", response_model=ApplicationOut)
def update_event(
    application_id: int,
    event_id: int,
    payload: EventUpdate,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    queue: Annotated[Queue, Depends(get_queue)],
) -> ApplicationOut:
    """Change a recorded state's note, date or status; omitted fields are kept."""
    application = _get_or_404(session, application_id)
    event = _event_or_404(application, event_id)
    if payload.status is not None and payload.status.upper() != event.status.key:
        _reject_initial_only(event.status.key)
        _reject_initial_only(payload.status)
        if payload.status.upper() == APPLIED_STATUS and any(
            e.status.key == APPLIED_STATUS for e in application.events
        ):
            raise HTTPException(status.HTTP_409_CONFLICT, "application is already APPLIED")
        event.status = _status_or_422(session, payload.status)
    if payload.note is not None:
        event.note = payload.note
    if payload.occurred_at is not None:
        event.occurred_at = payload.occurred_at
    session.commit()
    return _reload_out(session, application_id, request, queue)


@router.delete("/{application_id}/events/{event_id}", response_model=ApplicationOut)
def delete_event(
    application_id: int,
    event_id: int,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    queue: Annotated[Queue, Depends(get_queue)],
) -> ApplicationOut:
    application = _get_or_404(session, application_id)
    event = _event_or_404(application, event_id)
    _reject_initial_only(event.status.key)
    session.delete(event)
    session.commit()
    return _reload_out(session, application_id, request, queue)
