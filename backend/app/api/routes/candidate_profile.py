"""Candidate profile: a single free-text description of the candidate.

Several profiles may be stored, but only the latest one (highest ``id``) is relevant.
``GET /latest`` returns it; ``POST`` creates a new one; ``PATCH /{id}`` edits an existing one.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import CandidateProfile

router = APIRouter()


class CandidateProfileCreate(BaseModel):
    content: str = ""
    work_history_id: str | None = Field(default=None, max_length=256)


class CandidateProfileUpdate(BaseModel):
    """Partial update; omitted fields are left untouched."""

    content: str | None = None
    work_history_id: str | None = Field(default=None, max_length=256)


class CandidateProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    content: str
    work_history_id: str | None
    created_at: datetime
    updated_at: datetime


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
def latest_profile(session: Annotated[Session, Depends(get_session)]) -> CandidateProfile | None:
    """The current profile (most recently created), or ``null`` when none exists."""
    return session.scalars(select(CandidateProfile).order_by(CandidateProfile.id.desc()).limit(1)).first()


@router.get("/{profile_id}", response_model=CandidateProfileOut)
def get_profile(
    profile_id: int, session: Annotated[Session, Depends(get_session)]
) -> CandidateProfile:
    return _get_or_404(session, profile_id)


@router.patch("/{profile_id}", response_model=CandidateProfileOut)
def update_profile(
    profile_id: int,
    payload: CandidateProfileUpdate,
    session: Annotated[Session, Depends(get_session)],
) -> CandidateProfile:
    profile = _get_or_404(session, profile_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    session.commit()
    session.refresh(profile)
    return profile
