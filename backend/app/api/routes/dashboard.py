"""Numbers behind the Dashboard widgets.

``GET /api/dashboard/stats`` returns, in one request, the job-search flow (scored jobs down
to answered offers), a few headline counts, applications sent per week and the next
scheduled interview rounds. Everything is counted in SQL by ``app.services.dashboard``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.routes.jobs import inbox_count
from app.config import Settings, get_settings
from app.db import get_session
from app.schemas.dashboard import DashboardStats
from app.services import dashboard

router = APIRouter()


@router.get("/stats", response_model=DashboardStats)
def dashboard_stats(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DashboardStats:
    threshold = settings.relevant_job_threshold
    return dashboard.dashboard_stats(
        session,
        threshold=threshold,
        jobs_inbox=inbox_count(session, threshold),
        now=datetime.now(UTC),
    )
