"""``DELETE /api/cleanup``: remove old jobs and job parse results.

``older_than`` is a cut-off datetime; see :mod:`app.services.cleanup` for exactly what is
deleted and what is protected. Pass ``dry_run=true`` to only count the matches.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_session
from app.services.cleanup import Target, cleanup_old_jobs

router = APIRouter()


class CleanupResult(BaseModel):
    older_than: datetime
    dry_run: bool
    jobs_deleted: int
    job_parse_results_deleted: int


@router.delete("", response_model=CleanupResult)
def cleanup(
    session: Annotated[Session, Depends(get_session)],
    older_than: Annotated[
        datetime, Query(description="Delete records created before this datetime (ISO 8601)")
    ],
    target: Target = "all",
    dry_run: bool = False,
) -> CleanupResult:
    return CleanupResult(**asdict(cleanup_old_jobs(session, older_than, target, dry_run)))
