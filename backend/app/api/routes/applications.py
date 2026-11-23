"""Job applications made for evaluated jobs.

* ``POST /api/applications`` with ``{"job_evaluation_id": ...}`` creates the application
  (``409`` when the job already has one), records its initial state (``SHORTLISTED`` unless
  ``status`` says otherwise, ``null`` for none) and queues a tailored CV for the job. The
  interview rounds parsed from the job description (``job_parse_results.interview_steps``)
  become its planned rounds.
* ``GET /api/applications`` lists them newest first (``?status=INTERVIEW`` filters by
  current state, ``?q=acme`` by job title or company name); ``GET``/``PATCH``/``DELETE /api/applications/{id}`` work on one.
* ``POST /api/applications/{id}/events`` records a state change with its own note;
  ``PATCH``/``DELETE /api/applications/{id}/events/{event_id}`` edit or remove one.
  ``SHORTLISTED`` is only recorded at creation: it cannot be added, removed or switched
  to/from later (``422``), though its note and date can be edited. No state can be added
  while the current one is ``OFFER``, ``ACCEPTED``, ``REJECTED`` or ``CLOSED`` (``409``) until
  that state is removed.
  ``APPLIED`` can be recorded once, only while the current state is ``SHORTLISTED`` (``409``).
* Interview rounds: every ``INTERVIEW`` event is a round. ``PATCH /api/applications/{id}``
  with ``{"interview_rounds": 5}`` plans the rounds not held yet as *planned* events
  (``planned_events``, never the current state; ``0`` drops them) whose title, duration,
  schedule and note can be edited like any event. Recording ``INTERVIEW`` fills the first
  planned round; ``PATCH .../events/{id}`` with ``{"planned": false}`` holds a specific one.
  Deleting a planned round drops it; deleting a held one makes it planned again. Planned
  rounds stay (not held) while the application is ``OFFER``/``REJECTED``/``CLOSED`` but cannot be held
  then (``409``).
* ``POST /api/applications/{id}/accept`` with ``{"start_date": "2026-01-05"}`` accepts the
  offer of an application in ``OFFER`` (``409`` otherwise): it records ``ACCEPTED`` and adds
  the position to the work history (``work_history_id``) starting on that date, or on the
  application's ``start_date`` (set with ``PATCH``) when none is sent (``422`` without
  either). The entry is pending until it starts and is filled in from the application by
  ``app.tasks.work_history.prefill``. ``ACCEPTED`` cannot be added or switched to/from any
  other way (``422``); removing it deletes that work-history entry again.
* ``POST /api/applications/{id}/cv`` generates the CV again.
* ``GET /api/applications/statuses`` lists the available states;
  ``POST /api/applications/statuses`` adds a custom one.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Literal

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
from app.services.applications import (
    ACCEPTED_STATUS,
    APPLIED_STATUS,
    INTERVIEW_STATUS,
    EventRejected,
    accept_offer,
    ensure_statuses,
    held_at,
    held_rounds,
    plan_parsed_rounds,
    record_event,
    reject_accepted,
    reject_if_final,
    reject_initial_only,
    reject_out_of_order,
    set_interview_rounds,
    set_job_decision,
    status_by_key,
    undo_accept,
)
from app.services.candidate_profile import current_profile_ids
from app.services.evaluations import newest_evaluations
from app.services.relevance import relevance
from app.tasks.work_history import enqueue_prefill

router = APIRouter()

MAX_PAGE_SIZE = 200
MAX_INTERVIEW_ROUNDS = 20
DEFAULT_STATUS = "SHORTLISTED"


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
    title: str = ""
    """Kind of interview round."""
    duration_minutes: int | None = None
    occurred_at: datetime | None
    """When it happened; for a planned round the optional scheduled time."""
    source: Literal["manual", "gmail"] = "manual"
    """``gmail`` when the state was recorded automatically by the Gmail rejection monitor."""
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
    outdated: bool = False
    """Scored against an earlier work history; ``POST /api/jobs/{job_id}/rescore`` scores
    the job again."""


class ApplicationOut(BaseModel):
    id: int
    notes: str
    created_at: datetime
    updated_at: datetime
    status: StatusOut | None
    """Current state (that of the latest event); ``None`` when no state was recorded."""
    events: list[EventOut]
    """State history, oldest first (planned rounds left out)."""
    planned_events: list[EventOut] = []
    """Interview rounds planned but not held yet, in round order."""
    job: ApplicationJobOut
    evaluation: ApplicationEvaluationOut | None
    """The job's *newest* score (a re-score replaces the one the application was created
    from); ``None`` when the job has none left."""
    cv: GeneratedCvOut | None
    start_date: date | None = None
    """Agreed start date of the offered position, if known."""
    work_history_id: int | None = None
    """The work-history entry created by accepting the offer."""


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
    notes: str | None = None
    interview_rounds: int | None = Field(default=None, ge=0, le=MAX_INTERVIEW_ROUNDS)
    """Number of interview rounds, held + planned (``0`` drops the planned ones)."""
    start_date: date | None = None
    """Only applied when sent; ``null`` clears it."""


class AcceptOffer(BaseModel):
    start_date: date | None = None
    """Start of the position; the application's ``start_date`` when omitted."""


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
    """Only applied when sent; ``null`` clears the schedule of a planned round."""
    title: str | None = Field(default=None, max_length=128)
    duration_minutes: int | None = Field(default=None, ge=0, le=24 * 60)
    """Only applied when sent; ``null`` clears it."""
    planned: Literal[False] | None = None
    """``false`` marks a planned round as held."""

    _utc = field_validator("occurred_at")(_to_utc)


# --------------------------------------------------------------------------- helpers


def _query():
    return select(Application).options(
        joinedload(Application.job_parse_result).joinedload(JobParseResult.job).joinedload(Job.source),
        joinedload(Application.job_parse_result).joinedload(JobParseResult.company),
        joinedload(Application.generated_cv),
        selectinload(Application.events).joinedload(ApplicationEvent.status),
        selectinload(Application.work_entry),
    )


def _get_or_404(session: Session, application_id: int) -> Application:
    application = session.scalar(_query().where(Application.id == application_id))
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown application")
    return application


def _http_error(exc: EventRejected) -> HTTPException:
    code = status.HTTP_422_UNPROCESSABLE_CONTENT if exc.kind == "invalid" else status.HTTP_409_CONFLICT
    return HTTPException(code, str(exc))


def _status_or_422(session: Session, key: str) -> ApplicationStatus:
    try:
        return status_by_key(session, key)
    except EventRejected as exc:
        raise _http_error(exc) from exc


def _reject_fixed_status(key: str) -> None:
    """``SHORTLISTED`` and ``ACCEPTED`` cannot be switched to or from."""
    try:
        reject_initial_only(key)
        reject_accepted(key)
    except EventRejected as exc:
        raise _http_error(exc) from exc


def _cv_with_job(session: Session, cv_id: int) -> GeneratedCV:
    return session.scalar(
        select(GeneratedCV)
        .where(GeneratedCV.id == cv_id)
        .options(
            joinedload(GeneratedCV.job_parse_result).joinedload(JobParseResult.job).joinedload(Job.source),
            joinedload(GeneratedCV.job_parse_result).joinedload(JobParseResult.company),
        )
    )


def _event_out(e: ApplicationEvent) -> EventOut:
    return EventOut(
        id=e.id,
        status=StatusOut.model_validate(e.status),
        note=e.note or "",
        title=e.title or "",
        duration_minutes=e.duration_minutes,
        occurred_at=e.occurred_at,
        source=e.source or ApplicationEvent.SOURCE_MANUAL,
        created_at=e.created_at,
    )


def _reject_if_final(application: Application) -> None:
    try:
        reject_if_final(application)
    except EventRejected as exc:
        raise _http_error(exc) from exc


def _scores(session: Session, applications: list[Application]) -> dict[int, ApplicationEvaluationOut]:
    """``{application id: score}``: the newest evaluation of each application's job."""
    newest = newest_evaluations(session, [a.job_parse_result_id for a in applications])
    if not newest:
        return {}
    current_ids = current_profile_ids(session)
    threshold = get_settings().relevant_job_threshold
    scores = {}
    for application in applications:
        evaluation = newest.get(application.job_parse_result_id)
        if evaluation is not None:
            scores[application.id] = ApplicationEvaluationOut(
                id=evaluation.id,
                candidate_profile_id=evaluation.candidate_profile_id,
                relevance=relevance(evaluation.match_probability, threshold),
                outdated=evaluation.candidate_profile_id not in current_ids,
            )
    return scores


def _to_out(
    application: Application,
    request: Request,
    session: Session,
    queue: Queue,
    scores: dict[int, ApplicationEvaluationOut] | None = None,
) -> ApplicationOut:
    """``scores`` (see ``_scores``) lets a list compute every score in one go."""
    if scores is None:
        scores = _scores(session, [application])
    parsed = application.job_parse_result
    job = parsed.job
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
        events=[_event_out(e) for e in application.history],
        planned_events=[_event_out(e) for e in application.plan],
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
        evaluation=scores.get(application.id),
        cv=cv,
        start_date=application.start_date,
        work_history_id=application.work_entry.id if application.work_entry is not None else None,
    )


def _reload_out(session: Session, application_id: int, request: Request, queue: Queue) -> ApplicationOut:
    session.expire_all()
    return _to_out(_get_or_404(session, application_id), request, session, queue)


# --------------------------------------------------------------------------- statuses


@router.get("/statuses", response_model=list[StatusOut])
def list_statuses(session: Annotated[Session, Depends(get_session)]) -> list[StatusOut]:
    """Available application states in display order."""
    ensure_statuses(session)
    rows = session.scalars(select(ApplicationStatus).order_by(ApplicationStatus.position, ApplicationStatus.id)).all()
    return [StatusOut.model_validate(r) for r in rows]


@router.post("/statuses", response_model=StatusOut, status_code=status.HTTP_201_CREATED)
def create_status(payload: StatusCreate, session: Annotated[Session, Depends(get_session)]) -> StatusOut:
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
        select(Application.id).where(Application.job_parse_result_id == evaluation.job_parse_result_id)
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"application #{existing} already exists for this job")
    initial = _status_or_422(session, payload.status) if payload.status else None
    check_cv_inputs(session)

    application = Application(
        job_parse_result_id=evaluation.job_parse_result_id,
        job_evaluation_id=evaluation.id,
        notes=payload.notes,
    )
    if initial is not None:
        application.events.append(ApplicationEvent(status=initial, note=payload.status_note))
    plan_parsed_rounds(session, application, evaluation.job_parse_result)
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
    exclude_status: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> ApplicationPage:
    """Applications newest first (by creation); ``status`` keeps those whose current state matches,
    ``exclude_status`` (comma-separated) drops those in any of the listed states,
    ``q`` those whose job title or company name contains it (case-insensitive)."""
    applications = session.scalars(_query().order_by(Application.id.desc())).unique().all()
    if status_key:
        key = status_key.upper()
        applications = [a for a in applications if a.current_event and a.current_event.status.key == key]
    if exclude_status:
        excluded = {k.strip().upper() for k in exclude_status.split(",") if k.strip()}
        applications = [a for a in applications if not (a.current_event and a.current_event.status.key in excluded)]
    needle = (q or "").strip().casefold()
    if needle:
        applications = [a for a in applications if _matches(a, needle)]
    page = applications[offset : offset + limit]
    scores = _scores(session, page)
    return ApplicationPage(
        items=[_to_out(a, request, session, queue, scores) for a in page],
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
    """Replace the application's notes, its start date and/or its number of interview
    rounds (``422`` when fewer than the rounds already held)."""
    application = _get_or_404(session, application_id)
    if payload.notes is not None:
        application.notes = payload.notes
    if "start_date" in payload.model_fields_set:
        application.start_date = payload.start_date
    if payload.interview_rounds is not None:
        held = len(held_rounds(application))
        if 0 < payload.interview_rounds < held:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{held} interview round(s) already held")
        interview = _status_or_422(session, INTERVIEW_STATUS)
        set_interview_rounds(session, application, payload.interview_rounds, interview)
    session.commit()
    return _reload_out(session, application_id, request, queue)


@router.delete("/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_application(application_id: int, session: Annotated[Session, Depends(get_session)]) -> Response:
    """Delete the application and its state history (the generated CV is kept)."""
    session.delete(_get_or_404(session, application_id))
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{application_id}/accept", response_model=ApplicationOut)
def accept_application_offer(
    application_id: int,
    payload: AcceptOffer,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    queue: Annotated[Queue, Depends(get_queue)],
) -> ApplicationOut:
    """Accept the offer: record ``ACCEPTED``, add the position to the work history and queue
    filling it in from the application (see the module docstring)."""
    application = _get_or_404(session, application_id)
    try:
        entry = accept_offer(session, application, payload.start_date)
    except EventRejected as exc:
        raise _http_error(exc) from exc
    session.commit()
    enqueue_prefill(session, queue, entry)
    return _reload_out(session, application_id, request, queue)


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


@router.post("/{application_id}/events", response_model=ApplicationOut, status_code=status.HTTP_201_CREATED)
def add_event(
    application_id: int,
    payload: EventCreate,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    queue: Annotated[Queue, Depends(get_queue)],
) -> ApplicationOut:
    """Record a state change; it becomes the current state unless ``occurred_at`` puts it
    before a later one."""
    application = _get_or_404(session, application_id)
    try:
        record_event(session, application, payload.status, note=payload.note, occurred_at=payload.occurred_at)
    except EventRejected as exc:
        raise _http_error(exc) from exc
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
    """Change a recorded state's note, date, status, title or duration, or (``planned:
    false``) mark a planned round as held; omitted fields are kept."""
    application = _get_or_404(session, application_id)
    event = _event_or_404(application, event_id)
    sent = payload.model_fields_set
    if payload.status is not None and payload.status.upper() != event.status.key:
        if event.planned:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "a planned round is always INTERVIEW")
        _reject_fixed_status(event.status.key)
        _reject_fixed_status(payload.status)
        if payload.status.upper() == APPLIED_STATUS and any(e.status.key == APPLIED_STATUS for e in application.events):
            raise HTTPException(status.HTTP_409_CONFLICT, "application is already APPLIED")
        event.status = _status_or_422(session, payload.status)
    if not event.planned:
        new_key = payload.status or event.status.key
        new_time = payload.occurred_at if payload.occurred_at is not None else event.occurred_at
        try:
            reject_out_of_order(application, new_key, new_time, event=event)
        except EventRejected as exc:
            raise _http_error(exc) from exc
    if payload.note is not None:
        event.note = payload.note
    if "occurred_at" in sent and (payload.occurred_at is not None or event.planned):
        event.occurred_at = payload.occurred_at  # null only clears a planned round's schedule
    if payload.title is not None:
        event.title = payload.title.strip()
    if "duration_minutes" in sent:
        event.duration_minutes = payload.duration_minutes or None
    if payload.planned is False and event.planned:
        _reject_if_final(application)
        event.occurred_at = held_at(application, event)
        event.planned = False
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
    """Remove a state; a held interview round becomes a planned one again instead. Removing
    ``ACCEPTED`` also deletes the work-history entry accepting the offer created."""
    application = _get_or_404(session, application_id)
    event = _event_or_404(application, event_id)
    try:
        reject_initial_only(event.status.key)
    except EventRejected as exc:
        raise _http_error(exc) from exc
    if event.status.key == INTERVIEW_STATUS and not event.planned:
        event.planned = True
    else:
        if event.status.key == ACCEPTED_STATUS and not any(
            e.status.key == ACCEPTED_STATUS for e in application.history if e is not event
        ):
            undo_accept(session, application)
        session.delete(event)
    session.commit()
    return _reload_out(session, application_id, request, queue)
