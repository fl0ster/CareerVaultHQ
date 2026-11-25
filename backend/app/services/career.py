"""Roles held one after another at the same organisation (promotions and internal moves).

A position (``WorkHistoryEntry.KIND_JOB``) with a ``transition`` continues the candidate's
previous position at the same employer. That previous position is not stored: it is the
latest earlier position whose employer has the same normalised name
(``normalize_company_name``). Deriving the link keeps the JSON export free of ids, so a
``transition`` survives an export / import round trip. A role whose employer has no earlier
position simply stands on its own.

Linked roles form a *tenure*: the uninterrupted employment at one organisation, identified
by the id of its first role.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import WorkHistoryEntry
from app.services.companies import normalize_company_name


class LinkableEntry(Protocol):
    """What the linking reads of a work history entry."""

    @property
    def id(self) -> int: ...
    @property
    def kind(self) -> str: ...
    @property
    def employer(self) -> str: ...
    @property
    def date_start(self) -> date: ...
    @property
    def transition(self) -> str | None: ...


def previous_role_ids(entries: Iterable[LinkableEntry]) -> dict[int, int]:
    """``{role_id: previous_role_id}`` for every position with a ``transition`` that has an
    earlier position (by ``date_start``, then id) at the same employer."""
    by_employer: dict[str, list[LinkableEntry]] = {}
    for entry in entries:
        if entry.kind != WorkHistoryEntry.KIND_JOB:
            continue
        key = normalize_company_name(entry.employer or "")
        if key:
            by_employer.setdefault(key, []).append(entry)

    links: dict[int, int] = {}
    for roles in by_employer.values():
        roles.sort(key=lambda e: (e.date_start, e.id))
        for earlier, role in zip(roles, roles[1:], strict=False):
            if role.transition:
                links[role.id] = earlier.id
    return links


def tenure_ids(entries: Iterable[LinkableEntry]) -> dict[int, int]:
    """``{role_id: tenure_id}`` for every position: the id of the first role of the chain of
    promotions / moves it belongs to (its own id when it stands alone)."""
    entries = list(entries)
    links = previous_role_ids(entries)
    tenures: dict[int, int] = {}
    for entry in entries:
        if entry.kind != WorkHistoryEntry.KIND_JOB:
            continue
        root = entry.id
        while root in links:
            root = links[root]
        tenures[entry.id] = root
    return tenures


def job_entries(session: Session) -> list[WorkHistoryEntry]:
    """Every position, oldest first: the input of the linking."""
    return list(
        session.scalars(
            select(WorkHistoryEntry)
            .where(WorkHistoryEntry.kind == WorkHistoryEntry.KIND_JOB)
            .order_by(WorkHistoryEntry.date_start, WorkHistoryEntry.id)
        )
    )


def close_previous_role(session: Session, entry: WorkHistoryEntry) -> WorkHistoryEntry | None:
    """End the role ``entry`` continues when that role is still ongoing: a promotion or a
    move ends the previous position, so it ends the day before ``entry`` starts (never
    before its own start). Returns the role that was closed, if any; the caller commits."""
    if entry.kind != WorkHistoryEntry.KIND_JOB or not entry.transition:
        return None
    session.flush()  # give a new entry its id
    previous_id = previous_role_ids(job_entries(session)).get(entry.id)
    previous = session.get(WorkHistoryEntry, previous_id) if previous_id is not None else None
    if previous is None or previous.date_end is not None:
        return None
    previous.date_end = max(previous.date_start, entry.date_start - timedelta(days=1))
    return previous
