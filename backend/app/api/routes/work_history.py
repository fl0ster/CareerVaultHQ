"""CRUD for the user's work history.

Entries are returned newest first (by ``date_start``); a ``null`` ``date_end`` marks a
current position. ``tech`` is a free list of technology names.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import WorkHistoryEntry

router = APIRouter()


def _check_dates(date_start: date | None, date_end: date | None) -> None:
    if date_start is not None and date_end is not None and date_end < date_start:
        raise ValueError("date_end must not be earlier than date_start")


def _clean_tech(tech: list[str]) -> list[str]:
    """Strip whitespace, drop empties and duplicates while keeping order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in tech:
        name = item.strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out


class WorkHistoryCreate(BaseModel):
    date_start: date
    date_end: date | None = None
    employer: str = Field(min_length=1, max_length=256)
    role: str = Field(min_length=1, max_length=256)
    location: str | None = Field(default=None, max_length=256)
    tech: list[str] = Field(default_factory=list)
    context: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> WorkHistoryCreate:
        _check_dates(self.date_start, self.date_end)
        self.tech = _clean_tech(self.tech)
        return self


class WorkHistoryUpdate(BaseModel):
    """Partial update; omitted fields are left untouched, explicit ``null`` clears them."""

    date_start: date | None = None
    date_end: date | None = None
    employer: str | None = Field(default=None, min_length=1, max_length=256)
    role: str | None = Field(default=None, min_length=1, max_length=256)
    location: str | None = Field(default=None, max_length=256)
    tech: list[str] | None = None
    context: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> WorkHistoryUpdate:
        if self.tech is not None:
            self.tech = _clean_tech(self.tech)
        return self


class WorkHistoryExport(BaseModel):
    """Plain export shape; key names are part of the contract (note ``employeer``)."""

    date_start: str
    date_end: str | None
    employer: str
    role: str
    location: str | None
    tech: str
    context: str | None


class WorkHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date_start: date
    date_end: date | None
    employer: str
    role: str
    location: str | None
    tech: list[str]
    context: str | None
    created_at: datetime
    updated_at: datetime


def _get_or_404(session: Session, entry_id: int) -> WorkHistoryEntry:
    entry = session.get(WorkHistoryEntry, entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown work history entry")
    return entry


def _all_entries(session: Session) -> list[WorkHistoryEntry]:
    """All work history entries, most recent position first."""
    return list(
        session.scalars(
            select(WorkHistoryEntry).order_by(
                WorkHistoryEntry.date_start.desc(), WorkHistoryEntry.id.desc()
            )
        ).all()
    )


@router.get("", response_model=list[WorkHistoryOut])
def list_entries(session: Annotated[Session, Depends(get_session)]) -> list[WorkHistoryEntry]:
    """All work history entries, most recent position first."""
    return _all_entries(session)


@router.get("/json", response_model=list[WorkHistoryExport])
def export_entries(session: Annotated[Session, Depends(get_session)]) -> list[WorkHistoryExport]:
    """Work history as a bare JSON array with exactly the keys
    ``date_start, date_end, employer, role, location, tech, context``."""
    return [
        WorkHistoryExport(
            date_start=e.date_start.strftime("%b %Y"),
            date_end=e.date_end.strftime("%b %Y") if e.date_end else None,
            employer=e.employer,
            role=e.role,
            location=e.location,
            tech=str.join(", ", e.tech),
            context=e.context,
        )
        for e in _all_entries(session)
    ]


@router.post("", response_model=WorkHistoryOut, status_code=status.HTTP_201_CREATED)
def create_entry(
    payload: WorkHistoryCreate, session: Annotated[Session, Depends(get_session)]
) -> WorkHistoryEntry:
    entry = WorkHistoryEntry(**payload.model_dump())
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


@router.get("/{entry_id}", response_model=WorkHistoryOut)
def get_entry(entry_id: int, session: Annotated[Session, Depends(get_session)]) -> WorkHistoryEntry:
    return _get_or_404(session, entry_id)


@router.patch("/{entry_id}", response_model=WorkHistoryOut)
def update_entry(
    entry_id: int,
    payload: WorkHistoryUpdate,
    session: Annotated[Session, Depends(get_session)],
) -> WorkHistoryEntry:
    """Update the given fields only. Send ``"date_end": null`` to mark a position current."""
    entry = _get_or_404(session, entry_id)
    changes = payload.model_dump(exclude_unset=True)

    new_start = changes.get("date_start", entry.date_start)
    new_end = changes.get("date_end", entry.date_end)
    try:
        _check_dates(new_start, new_end)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    for field, value in changes.items():
        setattr(entry, field, value)
    session.commit()
    session.refresh(entry)
    return entry


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entry(entry_id: int, session: Annotated[Session, Depends(get_session)]) -> Response:
    entry = _get_or_404(session, entry_id)
    session.delete(entry)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
