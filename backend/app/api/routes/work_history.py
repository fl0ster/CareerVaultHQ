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
A position may continue the previous one at the same employer (``transition``: a promotion
or a role change, see ``app.services.career``); ``previous_role_id`` names that role, and
saving such a position ends the previous role when it is still ongoing.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import WorkHistoryEntry
from app.schemas.work_history import (
    EntryKind,
    Transition,
    WorkHistoryCreate,
    WorkHistoryExport,
    WorkHistoryImport,
    WorkHistoryUpdate,
    _check_dates,
    _check_employer,
    _check_kind_change,
    _format_month,
)
from app.services import work_journal
from app.services.career import close_previous_role, job_entries, previous_role_ids
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
    transition: Transition | None = None
    """The position is a promotion or role change within the employer of ``previous_role_id``."""
    previous_role_id: int | None = None
    """The role a position with a ``transition`` continues; ``None`` when there is no earlier
    position at the same employer (the role then stands on its own)."""
    journal_context: str | None = None
    """The position's description built from its work journal; used while ``context`` is blank."""
    journal_tech: list[str] = []
    """The technologies from its work journal; used while ``tech`` is empty."""
    journal_count: int = 0
    """Notes in the position's work journal."""
    last_journal_at: datetime | None = None
    """When the latest journal note was logged."""
    journal_overdue: bool = False
    """A current position without a journal note for a week."""

    @field_validator("journal_tech", mode="before")
    @classmethod
    def _no_journal_tech(cls, value: object) -> object:
        return [] if value is None else value


def _out(session: Session, entries: list[WorkHistoryEntry]) -> list[WorkHistoryOut]:
    """The entries as returned by the API, with their matched company."""
    companies = resolve_career_companies(session, entries)
    previous = previous_role_ids(job_entries(session))
    journals = work_journal.activity(session, [e.id for e in entries if e.kind == WorkHistoryEntry.KIND_JOB])
    now = datetime.now(UTC)
    out = []
    for entry in entries:
        item = WorkHistoryOut.model_validate(entry)
        if (journal := journals.get(entry.id)) is not None:
            item.journal_count, item.last_journal_at = journal.count, journal.last_at
        item.journal_overdue = work_journal.is_overdue(entry, item.last_journal_at, now)
        if (company := companies.get(entry.id)) is not None:
            item.company_id, item.company_tag = company.id, company.tag
        item.previous_role_id = previous.get(entry.id)
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
    ``kind, date_start, date_end, employer, role, location, tech, context, transition``."""
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
            transition=e.transition,
        )
        for e in _all_entries(session)
    ]


@router.post("/json", response_model=list[WorkHistoryOut], status_code=status.HTTP_201_CREATED)
def import_entries(
    payload: Annotated[list[WorkHistoryImport], Body()],
    session: Annotated[Session, Depends(get_session)],
    replace: bool = False,
) -> list[WorkHistoryOut]:
    """Import a JSON array in the shape produced by ``GET /json``. Entries are merged into
    the existing work history: an entry already there (same kind, employer, role and start,
    see ``_entry_key``) is skipped, so importing the same file twice adds nothing. Pass
    ``?replace=true`` to drop the existing work history first. The whole import is
    validated before anything is written, so a bad entry rejects the entire payload.
    Returns the entries created (``[]`` when all of them were duplicates)."""
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
        seen: set[tuple] = set()
    else:
        existing = session.execute(
            select(WorkHistoryEntry.kind, WorkHistoryEntry.employer, WorkHistoryEntry.role, WorkHistoryEntry.date_start)
        )
        seen = {_entry_key(*row) for row in existing}
    entries: list[WorkHistoryEntry] = []
    for create in creates:
        key = _entry_key(create.kind, create.employer, create.role, create.date_start)
        if key in seen:
            continue
        seen.add(key)
        entries.append(WorkHistoryEntry(**create.model_dump()))
    session.add_all(entries)
    session.commit()
    for entry in entries:
        session.refresh(entry)
    return _out(session, entries)


def _entry_key(kind: str, employer: str, role: str, date_start: date) -> tuple[str, str, str, date]:
    """What makes two entries the same one when merging an import."""
    return kind, employer.strip().casefold(), role.strip().casefold(), date_start


@router.post("", response_model=WorkHistoryOut, status_code=status.HTTP_201_CREATED)
def create_entry(payload: WorkHistoryCreate, session: Annotated[Session, Depends(get_session)]) -> WorkHistoryOut:
    entry = WorkHistoryEntry(**payload.model_dump())
    session.add(entry)
    close_previous_role(session, entry)
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
    """Update the given fields only. Send ``"date_end": null`` to mark a position current and
    ``"transition": null`` to make it a new employment again."""
    entry = _get_or_404(session, entry_id)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("kind", "") is None:
        del changes["kind"]
    if "employer" in changes:
        changes["employer"] = (changes["employer"] or "").strip()

    new_start = changes.get("date_start", entry.date_start)
    new_end = changes.get("date_end", entry.date_end)
    try:
        _check_kind_change(entry.kind, changes.get("kind", entry.kind))
        _check_dates(new_start, new_end)
        _check_employer(changes.get("kind", entry.kind), changes.get("employer", entry.employer))
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    if changes.get("kind", entry.kind) != WorkHistoryEntry.KIND_JOB:
        changes["transition"] = None
    for field, value in changes.items():
        setattr(entry, field, value)
    close_previous_role(session, entry)
    session.commit()
    session.refresh(entry)
    return _out(session, [entry])[0]


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entry(entry_id: int, session: Annotated[Session, Depends(get_session)]) -> Response:
    entry = _get_or_404(session, entry_id)
    session.delete(entry)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
