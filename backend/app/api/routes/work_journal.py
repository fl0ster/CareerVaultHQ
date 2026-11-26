"""The work journal of a position (``/api/work-history/{role_id}/journal``).

The user logs raw notes on what they did at a position; they are kept as written. The
polished monthly summaries and the description built from them (see
``app.services.work_journal``) are generated lazily: ``GET`` answers at once from what is
stored and says what is ``stale``; ``POST .../refresh`` regenerates the stale parts with the
LLM (the UI calls it when the journal is opened and something is stale).
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import WorkHistoryEntry, WorkJournalEntry
from app.services import work_journal
from app.services.openrouter import OpenRouterNotConfigured, OpenRouterService, get_openrouter

log = logging.getLogger(__name__)

router = APIRouter()

MAX_NOTE_CHARS = work_journal.MAX_NOTE_CHARS


class JournalEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    logged_on: date
    body: str
    created_at: datetime
    updated_at: datetime


class JournalMonthOut(BaseModel):
    month: date
    """First day of the month."""
    summary: str | None
    """The polished summary; ``None`` until it is generated."""
    accomplishments: list[str]
    tech: list[str]
    generated_at: datetime | None
    stale: bool
    """The notes changed since the summary was generated (or it never was)."""


class JournalOut(BaseModel):
    role_id: int
    entries: list[JournalEntryOut]
    """The raw notes, newest first."""
    months: list[JournalMonthOut]
    """One per month with notes, newest first."""
    journal_context: str | None
    """The position's description built from the monthly summaries."""
    journal_tech: list[str]
    context_overridden: bool
    """The user wrote their own description, which is used instead of ``journal_context``."""
    tech_overridden: bool
    """The user set their own technologies, which are used instead of ``journal_tech``."""
    stale: bool
    """Something needs regenerating: call ``POST .../refresh``."""
    warnings: list[str] = []
    """What a refresh could not regenerate (the previous version is kept)."""


def _note_body(value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError("the note is empty")
    return text


class JournalEntryCreate(BaseModel):
    body: str = Field(max_length=MAX_NOTE_CHARS)
    logged_on: date | None = None
    """The day the work happened; defaults to today."""

    @field_validator("body")
    @classmethod
    def _body(cls, value: str) -> str:
        return _note_body(value)


class JournalEntryUpdate(BaseModel):
    body: str | None = Field(default=None, max_length=MAX_NOTE_CHARS)
    logged_on: date | None = None

    @field_validator("body")
    @classmethod
    def _body(cls, value: str | None) -> str | None:
        return None if value is None else _note_body(value)


def _role_or_404(session: Session, role_id: int) -> WorkHistoryEntry:
    role = session.get(WorkHistoryEntry, role_id)
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown work history entry")
    if role.kind != WorkHistoryEntry.KIND_JOB:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "only positions have a work journal")
    return role


def _note_or_404(session: Session, role: WorkHistoryEntry, note_id: int) -> WorkJournalEntry:
    note = session.get(WorkJournalEntry, note_id)
    if note is None or note.work_history_id != role.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown journal entry")
    return note


def _check_day(role: WorkHistoryEntry, day: date) -> None:
    if day > date.today():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "the note cannot be dated in the future")
    if day < role.date_start or (role.date_end is not None and day > role.date_end):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "the note must be dated within the position")


def _journal(role: WorkHistoryEntry, warnings: list[str] | None = None) -> JournalOut:
    by_month = work_journal.notes_by_month(role.journal_entries)
    built = {m.month: m for m in role.journal_months}
    months = []
    for month in sorted(by_month, reverse=True):
        row = built.get(month)
        months.append(
            JournalMonthOut(
                month=month,
                summary=row.summary if row is not None else None,
                accomplishments=list(row.accomplishments or []) if row is not None else [],
                tech=list(row.tech or []) if row is not None else [],
                generated_at=row.generated_at if row is not None else None,
                stale=row is None or row.source_hash != work_journal.notes_hash(by_month[month]),
            )
        )
    return JournalOut(
        role_id=role.id,
        entries=[JournalEntryOut.model_validate(n) for n in role.journal_entries],
        months=months,
        journal_context=role.journal_context,
        journal_tech=list(role.journal_tech or []),
        context_overridden=bool((role.context or "").strip()),
        tech_overridden=bool(role.tech),
        stale=work_journal.is_stale(role),
        warnings=warnings or [],
    )


@router.get("/{role_id}/journal", response_model=JournalOut)
def get_journal(role_id: int, session: Annotated[Session, Depends(get_session)]) -> JournalOut:
    """The position's notes and what was generated from them, as stored (no LLM call)."""
    return _journal(_role_or_404(session, role_id))


@router.post("/{role_id}/journal/refresh", response_model=JournalOut)
def refresh_journal(
    role_id: int,
    session: Annotated[Session, Depends(get_session)],
    service: Annotated[OpenRouterService, Depends(get_openrouter)],
) -> JournalOut:
    """Regenerate the stale monthly summaries and description with the LLM. What cannot be
    regenerated keeps its previous version and is listed in ``warnings``. 503 when OpenRouter
    is not configured."""
    role = _role_or_404(session, role_id)
    try:
        warnings = work_journal.refresh_journal(session, role, service)
    except OpenRouterNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    session.refresh(role)
    return _journal(role, warnings)


@router.post("/{role_id}/journal", response_model=JournalEntryOut, status_code=status.HTTP_201_CREATED)
def add_note(
    role_id: int, payload: JournalEntryCreate, session: Annotated[Session, Depends(get_session)]
) -> JournalEntryOut:
    """Log a note on the position (dated today unless ``logged_on`` says otherwise)."""
    role = _role_or_404(session, role_id)
    day = payload.logged_on or date.today()
    _check_day(role, day)
    note = WorkJournalEntry(work_history_id=role.id, logged_on=day, body=payload.body)
    session.add(note)
    session.commit()
    session.refresh(note)
    return JournalEntryOut.model_validate(note)


@router.patch("/{role_id}/journal/{note_id}", response_model=JournalEntryOut)
def update_note(
    role_id: int, note_id: int, payload: JournalEntryUpdate, session: Annotated[Session, Depends(get_session)]
) -> JournalEntryOut:
    role = _role_or_404(session, role_id)
    note = _note_or_404(session, role, note_id)
    if payload.logged_on is not None:
        _check_day(role, payload.logged_on)
        note.logged_on = payload.logged_on
    if payload.body is not None:
        note.body = payload.body
    session.commit()
    session.refresh(note)
    return JournalEntryOut.model_validate(note)


@router.delete("/{role_id}/journal/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(role_id: int, note_id: int, session: Annotated[Session, Depends(get_session)]) -> Response:
    role = _role_or_404(session, role_id)
    session.delete(_note_or_404(session, role, note_id))
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
