"""Counts behind the badges in the app's menu.

``GET /api/nav/counts`` returns, in one cheap request, how many jobs wait in the Jobs inbox
and how many applications there are in total and in the interview / offer stages. The
frontend polls it, so the badges follow changes made by background tasks (scrapes,
evaluations, the Gmail monitor) as well as those made in the UI.
"""

from __future__ import annotations

from collections import Counter
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.routes.jobs import inbox_count
from app.config import Settings, get_settings
from app.db import get_session
from app.models import Application, ApplicationEvent

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
    applications = session.scalars(
        select(Application).options(selectinload(Application.events).joinedload(ApplicationEvent.status))
    ).all()
    stages = Counter(a.current_event.status.key for a in applications if a.current_event is not None)
    return NavCounts(
        jobs_inbox=inbox_count(session, settings.relevant_job_threshold),
        applications=len(applications),
        interviews=stages[INTERVIEW_STATUS],
        offers=stages[OFFER_STATUS],
    )
