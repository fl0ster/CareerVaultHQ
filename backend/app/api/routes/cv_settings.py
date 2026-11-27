"""CV settings: the consent clause printed at the end of every CV and the timeline rules
(see ``app.tasks.cv.history``).

* ``GET /api/cv-settings`` returns the consent clause, the rules in effect, the defaults and
  which rules are overridden.
* ``PUT /api/cv-settings`` replaces them; a ``null`` rule (or one equal to its default)
  goes back to the default.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.models import CVSettings
from app.services.cv_settings import TIMELINE_FIELDS, get_cv_settings, timeline_defaults, timeline_rules

router = APIRouter()


class TimelineRules(BaseModel):
    max_entries: int
    min_entries: int
    high_relevance: float
    irrelevant_relevance: float
    min_months: int


class CvSettingsOut(BaseModel):
    consent_text: str
    rules: TimelineRules
    """The rules in effect (overrides, or the defaults)."""
    defaults: TimelineRules
    overridden: list[str]
    """Names of the rules that differ from their defaults."""


class CvSettingsIn(BaseModel):
    consent_text: str = ""
    max_entries: int | None = Field(default=None, ge=1, le=20)
    min_entries: int | None = Field(default=None, ge=0, le=20)
    high_relevance: float | None = Field(default=None, ge=0, le=1)
    irrelevant_relevance: float | None = Field(default=None, ge=0, le=1)
    min_months: int | None = Field(default=None, ge=0, le=120)


def _out(row: CVSettings, settings: Settings) -> CvSettingsOut:
    return CvSettingsOut(
        consent_text=row.consent_text,
        rules=TimelineRules(**timeline_rules(row, settings)),
        defaults=TimelineRules(**timeline_defaults(settings)),
        overridden=[name for name in TIMELINE_FIELDS if getattr(row, name) is not None],
    )


@router.get("", response_model=CvSettingsOut)
def get_cv_settings_route(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CvSettingsOut:
    return _out(get_cv_settings(session), settings)


@router.put("", response_model=CvSettingsOut)
def put_cv_settings(
    payload: CvSettingsIn,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CvSettingsOut:
    defaults = timeline_defaults(settings)
    rule = {name: defaults[name] if getattr(payload, name) is None else getattr(payload, name) for name in TIMELINE_FIELDS}
    if rule["min_entries"] > rule["max_entries"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Minimum roles cannot exceed maximum roles.")
    if rule["irrelevant_relevance"] > rule["high_relevance"]:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The irrelevant threshold cannot exceed the high-relevance threshold."
        )
    row = get_cv_settings(session)
    row.consent_text = payload.consent_text.strip()
    for name in TIMELINE_FIELDS:
        value = getattr(payload, name)
        setattr(row, name, None if value is None or value == defaults[name] else value)
    session.commit()
    return _out(row, settings)
