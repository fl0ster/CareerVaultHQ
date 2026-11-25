"""Request / exchange shapes of the work history, shared by ``api.routes.work_history``
and the tasks that produce them (``tasks.cv_import``). Kept outside ``app.api`` so a task
can import them without loading every router (which imports the tasks back)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

EntryKind = Literal["job", "education", "certificate"]
"""Kind of career event; mirrors ``WorkHistoryEntry.KINDS``."""

Transition = Literal["promotion", "role_change"]
"""How a position continues the previous one at the same employer; mirrors
``WorkHistoryEntry.TRANSITIONS`` (see ``app.services.career``)."""


def _check_employer(kind: str, employer: str) -> None:
    """Only a job needs its organisation; a degree or certificate may leave it blank."""
    if kind == "job" and not employer.strip():
        raise ValueError("employer is required for a job")


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
    kind: EntryKind = "job"
    date_start: date
    date_end: date | None = None
    """``None``: ongoing job / education, or a certificate without a duration."""
    employer: str = Field(default="", max_length=256)
    """Employer, institution or issuer; required for a job only."""
    role: str = Field(min_length=1, max_length=256)
    """Role, degree or certificate name."""
    location: str | None = Field(default=None, max_length=256)
    tech: list[str] = Field(default_factory=list)
    context: str | None = None
    transition: Transition | None = None
    """A promotion or role change within the employer of the previous position; positions only."""

    @model_validator(mode="after")
    def _validate(self) -> WorkHistoryCreate:
        _check_dates(self.date_start, self.date_end)
        self.employer = self.employer.strip()
        _check_employer(self.kind, self.employer)
        self.tech = _clean_tech(self.tech)
        if self.kind != "job":
            self.transition = None
        return self


class WorkHistoryUpdate(BaseModel):
    """Partial update; omitted fields are left untouched, explicit ``null`` clears them."""

    kind: EntryKind | None = None
    date_start: date | None = None
    date_end: date | None = None
    employer: str | None = Field(default=None, max_length=256)
    role: str | None = Field(default=None, min_length=1, max_length=256)
    location: str | None = Field(default=None, max_length=256)
    tech: list[str] | None = None
    context: str | None = None
    transition: Transition | None = None

    @model_validator(mode="after")
    def _validate(self) -> WorkHistoryUpdate:
        if self.tech is not None:
            self.tech = _clean_tech(self.tech)
        return self


MONTH_FORMAT = "%b %Y"
"""Date format used by the JSON export/import (``Jan 2020``)."""


def _format_month(value: date | None) -> str | None:
    return value.strftime(MONTH_FORMAT) if value else None


def _parse_month(value: str | None) -> date | None:
    """Inverse of :func:`_format_month`; also accepts ISO dates (``2020-01-15``)."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    for fmt in (MONTH_FORMAT, "%B %Y", "%Y-%m-%d", "%Y-%m"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {value!r}; expected e.g. 'Jan 2020'")


class WorkHistoryExport(BaseModel):
    """Plain export shape; key names are part of the contract."""

    kind: EntryKind
    date_start: str
    date_end: str | None
    employer: str
    role: str
    location: str | None
    tech: str
    context: str | None
    transition: Transition | None


class WorkHistoryImport(BaseModel):
    """One entry of an import payload. Same shape as :class:`WorkHistoryExport`, so an
    export can be fed straight back in; ``tech`` may be either a comma separated string
    or a list. ``kind`` defaults to ``job`` and ``transition`` to none, so older exports still
    import (and older versions importing a newer export ignore ``transition``)."""

    kind: EntryKind = "job"
    date_start: str
    date_end: str | None = None
    employer: str = Field(default="", max_length=256)
    role: str = Field(min_length=1, max_length=256)
    location: str | None = Field(default=None, max_length=256)
    tech: str | list[str] = ""
    context: str | None = None
    transition: Transition | None = None

    @field_validator("transition", mode="before")
    @classmethod
    def _blank_transition(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    def to_create(self) -> WorkHistoryCreate:
        """Convert to the validated create payload; raises ``ValueError`` on bad dates."""
        tech = self.tech.split(",") if isinstance(self.tech, str) else self.tech
        date_start = _parse_month(self.date_start)
        if date_start is None:
            raise ValueError("date_start is required")
        return WorkHistoryCreate(
            kind=self.kind,
            date_start=date_start,
            date_end=_parse_month(self.date_end),
            employer=self.employer,
            role=self.role,
            location=self.location,
            tech=tech,
            context=self.context,
            transition=self.transition,
        )
