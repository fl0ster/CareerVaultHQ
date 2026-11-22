"""Scrape sources: the ``scrape_sources`` rows mirroring the plugin modules in
``app.tasks.scrape.sources``.

``GET /api/sources`` syncs the rows with the modules on disk first (so a freshly dropped
file shows up immediately) and returns them with their health and relevance for the latest
candidate profile. ``PATCH /api/sources/{key}`` edits the user-controlled fields
(``enabled``, ``scrape_interval_seconds``). To run one, use
``POST /api/scrape`` with ``{"source": key}``; enabled sources are also scraped periodically by
``app.scheduler`` (``next_scrape_at`` is its plan).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.models import ScrapeSource
from app.services.sources import (
    Relevance,
    get_source,
    is_scrape_target,
    source_relevance,
    sync_sources,
)

router = APIRouter()


class SourceRelevance(BaseModel):
    job_count: int = 0
    evaluated_count: int = 0
    avg_match: float | None = None
    """Mean ``match_probability`` of the source's jobs against the latest profile."""
    good_match_share: float | None = None
    """Share (0-1) of evaluated jobs scored as a good match."""


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    name: str
    url: str | None
    enabled: bool
    module_error: str | None
    health: str
    """``unknown`` / ``healthy`` / ``degraded`` / ``failing`` / ``broken``."""
    last_run_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None
    last_scraped_count: int | None
    last_new_count: int | None
    consecutive_failures: int
    scrape_interval_seconds: int | None
    """Per-source scrape interval; ``None`` means the default below applies."""
    default_scrape_interval_seconds: int = 0
    """``Settings.scrape_interval_seconds``, used when ``scrape_interval_seconds`` is empty."""
    next_scrape_at: datetime | None
    """When the scheduler runs the source next (``None`` while disabled or not yet planned)."""
    updated_at: datetime
    relevance: SourceRelevance = SourceRelevance()

    @field_validator("last_run_at", "last_success_at", "next_scrape_at", "updated_at", mode="after")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        """SQLite returns naive datetimes; they are UTC, so say so in the JSON."""
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


MIN_SCRAPE_INTERVAL_SECONDS = 15 * 60


class SourceUpdate(BaseModel):
    enabled: bool | None = None
    scrape_interval_seconds: int | None = Field(default=None, ge=MIN_SCRAPE_INTERVAL_SECONDS)
    """Send ``null`` to go back to the default interval."""


NULLABLE_FIELDS = frozenset({"scrape_interval_seconds"})
"""Fields of ``SourceUpdate`` where an explicit ``null`` is a value, not "leave unchanged"."""


def _to_out(row: ScrapeSource, relevance: Relevance | None) -> SourceOut:
    out = SourceOut.model_validate(row)
    out.default_scrape_interval_seconds = get_settings().scrape_interval_seconds
    if not row.enabled:
        out.next_scrape_at = None
    if relevance is not None:
        out.relevance = SourceRelevance(**relevance.__dict__)
    return out


@router.get("", response_model=list[SourceOut])
def list_sources(session: Annotated[Session, Depends(get_session)]) -> list[SourceOut]:
    """Every scrape source (by key), synced with the modules on disk. The ``manual``
    pseudo-source of hand-entered jobs is not a scrape target and is left out."""
    rows = sync_sources(session)
    relevance = source_relevance(session)
    return [_to_out(row, relevance.get(row.id)) for row in rows if is_scrape_target(row)]


@router.patch("/{key}", response_model=SourceOut)
def update_source(key: str, payload: SourceUpdate, session: Annotated[Session, Depends(get_session)]) -> SourceOut:
    """Change ``enabled`` and/or ``scrape_interval_seconds`` of one source.

    Changing the interval or (re-)enabling the source clears ``next_scrape_at`` so the
    scheduler re-plans it from ``last_run_at`` with the new settings.
    """
    row = get_source(session, key)
    if row is None or not is_scrape_target(row):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown source")
    replan = False
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is None and field not in NULLABLE_FIELDS:
            continue
        if getattr(row, field) == value:
            continue
        setattr(row, field, value)
        if field == "scrape_interval_seconds" or (field == "enabled" and value):
            replan = True
    if replan:
        row.next_scrape_at = None
    session.commit()
    session.refresh(row)
    return _to_out(row, source_relevance(session).get(row.id))
