"""CRUD for the user's career timeline ("My Career"): positions, education and certificates.

Every entry has a ``kind`` (``job``, ``education`` or ``certificate``). Entries are
returned newest first (by ``date_start``); a ``null`` ``date_end`` marks a current position
or ongoing education, and a certificate that is a single point in time. ``tech`` is a free
list of technology names. An entry starting in the future is ``pending``: it is left out
of CVs and the candidate profile until it starts.
Entries created by accepting an offer (``POST /api/applications/{id}/accept``) carry that
``application_id`` and the progress of filling them in from it (``prefill_state``).
A position's employer is resolved to its company (created when it is not known yet, like a
company scraped from a job page): ``company_id`` and ``company_tag`` name it.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import WorkHistoryEntry
from app.schemas.work_history import (
    EntryKind,
    WorkHistoryCreate,
    WorkHistoryExport,
    WorkHistoryImport,
    WorkHistoryUpdate,
    _check_dates,
    _check_employer,
    _format_month,
)
from app.services.companies import resolve_career_companies

router = APIRouter()


class WorkHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: EntryKind
    date_start: date
    date_end: date | None
    employer: str
    role: str
    location: str | None
    tech: list[str]
    context: str | None
    application_id: int | None = None
    """The application whose accepted offer created the entry."""
    pending: bool = False
    """The position starts in the future (see the module docstring)."""
    prefill_state: Literal["queued", "done", "failed"] | None = None
    """Filling the entry in from its application with the LLM; ``None`` for manual entries."""
    created_at: datetime
    updated_at: datetime
    company_id: int | None = None
    """The company of the position's employer (always ``None`` for education and
    certificates)."""
    company_tag: str | None = None
    """That company's tag."""


def _out(session: Session, entries: list[WorkHistoryEntry]) -> list[WorkHistoryOut]:
    """The entries as returned by the API, with their matched company."""
    companies = resolve_career_companies(session, entries)
    out = []
    for entry in entries:
        item = WorkHistoryOut.model_validate(entry)
        if (company := companies.get(entry.id)) is not None:
            item.company_id, item.company_tag = company.id, company.tag
        out.append(item)
    return out


def _get_or_404(session: Session, entry_id: int) -> WorkHistoryEntry:
    entry = session.get(WorkHistoryEntry, entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown work history entry")
    return entry


def _all_entries(session: Session) -> list[WorkHistoryEntry]:
    """All work history entries, most recent position first."""
    return list(
        session.scalars(
            select(WorkHistoryEntry).order_by(WorkHistoryEntry.date_start.desc(), WorkHistoryEntry.id.desc())
        ).all()
    )


@router.get("", response_model=list[WorkHistoryOut])
def list_entries(session: Annotated[Session, Depends(get_session)]) -> list[WorkHistoryOut]:
    """All work history entries, most recent position first."""
    return _out(session, _all_entries(session))


@router.get("/json", response_model=list[WorkHistoryExport])
def export_entries(session: Annotated[Session, Depends(get_session)]) -> list[WorkHistoryExport]:
    """Work history as a bare JSON array with exactly the keys
    ``kind, date_start, date_end, employer, role, location, tech, context``."""
    return [
        WorkHistoryExport(
            kind=e.kind,
            date_start=_format_month(e.date_start),
            date_end=_format_month(e.date_end),
            employer=e.employer,
            role=e.role,
            location=e.location,
            tech=str.join(", ", e.tech),
            context=e.context,
        )
        for e in _all_entries(session)
    ]


@router.post("/json", response_model=list[WorkHistoryOut], status_code=status.HTTP_201_CREATED)
def import_entries(
    payload: Annotated[list[WorkHistoryImport], Body()],
    session: Annotated[Session, Depends(get_session)],
    replace: bool = False,
) -> list[WorkHistoryOut]:
    """Import a JSON array in the shape produced by ``GET /json``. Entries are appended;
    pass ``?replace=true`` to drop the existing work history first. The whole import is
    validated before anything is written, so a bad entry rejects the entire payload."""
    if not payload:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "no entries to import")
    creates: list[WorkHistoryCreate] = []
    for index, item in enumerate(payload):
        try:
            creates.append(item.to_create())
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"entry {index}: {exc}") from exc

    if replace:
        session.execute(delete(WorkHistoryEntry))
    entries = [WorkHistoryEntry(**c.model_dump()) for c in creates]
    session.add_all(entries)
    session.commit()
    for entry in entries:
        session.refresh(entry)
    return _out(session, entries)


@router.post("", response_model=WorkHistoryOut, status_code=status.HTTP_201_CREATED)
def create_entry(payload: WorkHistoryCreate, session: Annotated[Session, Depends(get_session)]) -> WorkHistoryOut:
    entry = WorkHistoryEntry(**payload.model_dump())
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return _out(session, [entry])[0]


@router.get("/{entry_id}", response_model=WorkHistoryOut)
def get_entry(entry_id: int, session: Annotated[Session, Depends(get_session)]) -> WorkHistoryOut:
    return _out(session, [_get_or_404(session, entry_id)])[0]


@router.patch("/{entry_id}", response_model=WorkHistoryOut)
def update_entry(
    entry_id: int,
    payload: WorkHistoryUpdate,
    session: Annotated[Session, Depends(get_session)],
) -> WorkHistoryOut:
    """Update the given fields only. Send ``"date_end": null`` to mark a position current."""
    entry = _get_or_404(session, entry_id)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("kind", "") is None:
        del changes["kind"]
    if "employer" in changes:
        changes["employer"] = (changes["employer"] or "").strip()

    new_start = changes.get("date_start", entry.date_start)
    new_end = changes.get("date_end", entry.date_end)
    try:
        _check_dates(new_start, new_end)
        _check_employer(changes.get("kind", entry.kind), changes.get("employer", entry.employer))
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    for field, value in changes.items():
        setattr(entry, field, value)
    session.commit()
    session.refresh(entry)
    return _out(session, [entry])[0]


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entry(entry_id: int, session: Annotated[Session, Depends(get_session)]) -> Response:
    entry = _get_or_404(session, entry_id)
    session.delete(entry)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
