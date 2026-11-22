"""Counts behind the badges in the app's menu.

``GET /api/nav/counts`` returns, in one cheap request, how many jobs wait in the Jobs inbox
and how many applications there are in total and in the interview / offer stages. The
frontend polls it, so the badges follow changes made by background tasks (scrapes,
evaluations, the Gmail monitor) as well as those made in the UI.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.routes.jobs import inbox_count
from app.config import Settings, get_settings
from app.db import get_session
from app.services.applications import application_count, current_stage_counts

router = APIRouter()

INTERVIEW_STATUS = "INTERVIEW"
OFFER_STATUS = "OFFER"


class NavCounts(BaseModel):
    jobs_inbox: int
    """Undecided relevant jobs (the Jobs inbox)."""
    applications: int
    interviews: int
    """Applications whose current state is ``INTERVIEW``."""
    offers: int
    """Applications whose current state is ``OFFER``."""


@router.get("/counts", response_model=NavCounts)
def nav_counts(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> NavCounts:
    stages = current_stage_counts(session)
    return NavCounts(
        jobs_inbox=inbox_count(session, settings.relevant_job_threshold),
        applications=application_count(session),
        interviews=stages.get(INTERVIEW_STATUS, 0),
        offers=stages.get(OFFER_STATUS, 0),
    )
