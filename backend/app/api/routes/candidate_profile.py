"""Candidate profile: a single free-text description of the candidate.

Profiles are only ever generated from the work history, lazily: ``GET /latest`` (like the
evaluation task) regenerates the profile first when it is missing or the work history
changed since it was built (see ``app.services.candidate_profile``). Several profiles may be
stored, but only the latest one (highest ``id``) is relevant.

A new profile makes every parsed job unevaluated again, so a first batch of
``evaluate_pending_jobs`` is enqueued straight away; the scheduler's periodic catch-up run
scores the rest.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from rq import Queue
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.models import CandidateProfile
from app.queue import get_queue
from app.services.candidate_profile import current_profile
from app.services.openrouter import OpenRouterError, OpenRouterService, get_openrouter
from app.tasks.evaluate import evaluate_pending_jobs

log = logging.getLogger(__name__)

router = APIRouter()

EVALUATE_TIMEOUT = 3600
"""RQ ``job_timeout`` for the evaluation batch enqueued after a profile is created."""


class CandidateProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    content: str
    work_history_id: str | None
    created_at: datetime
    updated_at: datetime


def enqueue_evaluation(queue: Queue, settings: Settings, profile: CandidateProfile) -> str | None:
    """Enqueue ``evaluate_pending_jobs(evaluate_batch_size)`` so jobs get scored against the
    new profile without waiting for the scheduler. Returns the RQ job id, or ``None`` when
    the queue is unreachable: the profile is saved either way and the scheduler's catch-up
    run evaluates the jobs later."""
    try:
        job = queue.enqueue(
            evaluate_pending_jobs,
            settings.evaluate_batch_size,
            job_id=uuid.uuid4().hex,
            job_timeout=EVALUATE_TIMEOUT,
            result_ttl=settings.job_result_ttl,
            failure_ttl=settings.job_result_ttl,
            meta={"candidate_profile_id": profile.id},
            description=f"evaluate pending jobs against profile {profile.id}",
        )
    except Exception:
        log.exception("Could not enqueue evaluation for candidate profile %d", profile.id)
        return None
    return job.id


def _get_or_404(session: Session, profile_id: int) -> CandidateProfile:
    profile = session.get(CandidateProfile, profile_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown candidate profile")
    return profile


@router.get("", response_model=list[CandidateProfileOut])
def list_profiles(session: Annotated[Session, Depends(get_session)]) -> list[CandidateProfile]:
    """All profiles, newest first."""
    return list(session.scalars(select(CandidateProfile).order_by(CandidateProfile.id.desc())).all())


@router.get("/latest", response_model=CandidateProfileOut | None)
def latest_profile(
    session: Annotated[Session, Depends(get_session)],
    ai_service: Annotated[OpenRouterService, Depends(get_openrouter)],
    queue: Annotated[Queue, Depends(get_queue)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CandidateProfile | None:
    """The current profile, or ``null`` when there is neither a profile nor a work history.

    When the profile is missing or older than the work history it is regenerated first
    (and a batch of job evaluations against it is enqueued); 502 when that fails.
    """
    try:
        profile, created = current_profile(session, ai_service)
    except OpenRouterError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    if created and profile is not None:
        enqueue_evaluation(queue, settings, profile)
    return profile


@router.get("/{profile_id}", response_model=CandidateProfileOut)
def get_profile(profile_id: int, session: Annotated[Session, Depends(get_session)]) -> CandidateProfile:
    return _get_or_404(session, profile_id)
