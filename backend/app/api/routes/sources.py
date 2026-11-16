"""Scrape sources: the ``scrape_sources`` rows mirroring the plugin modules in
``app.tasks.scrape.sources``.

``GET /api/sources`` syncs the rows with the modules on disk first (so a freshly dropped
file shows up immediately) and returns them with their health and relevance for the latest
candidate profile. ``PATCH /api/sources/{key}`` edits the user-controlled fields
(``enabled``, ``priority``). To run one, use ``POST /api/scrape`` with ``{"source": key}``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import ScrapeSource
from app.services.sources import Relevance, get_source, source_relevance, sync_sources

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
    priority: int
    module_error: str | None
    health: str
    """``unknown`` / ``healthy`` / ``degraded`` / ``failing`` / ``broken``."""
    last_run_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None
    last_scraped_count: int | None
    last_new_count: int | None
    consecutive_failures: int
    updated_at: datetime
    relevance: SourceRelevance = SourceRelevance()


class SourceUpdate(BaseModel):
    enabled: bool | None = None
    priority: int | None = None


def _to_out(row: ScrapeSource, relevance: Relevance | None) -> SourceOut:
    out = SourceOut.model_validate(row)
    if relevance is not None:
        out.relevance = SourceRelevance(**relevance.__dict__)
    return out


@router.get("", response_model=list[SourceOut])
def list_sources(session: Annotated[Session, Depends(get_session)]) -> list[SourceOut]:
    """Every source (highest priority first), synced with the modules on disk."""
    rows = sync_sources(session)
    relevance = source_relevance(session)
    return [_to_out(row, relevance.get(row.id)) for row in rows]


@router.patch("/{key}", response_model=SourceOut)
def update_source(
    key: str, payload: SourceUpdate, session: Annotated[Session, Depends(get_session)]
) -> SourceOut:
    """Change ``enabled`` and/or ``priority`` of one source."""
    row = get_source(session, key)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown source")
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(row, field, value)
    session.commit()
    session.refresh(row)
    return _to_out(row, source_relevance(session).get(row.id))
