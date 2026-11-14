"""Candidate profile: a single free-text description of the candidate.

Several profiles may be stored, but only the latest one (highest ``id``) is relevant.
``GET /latest`` returns it; ``POST`` creates a new one; ``PATCH /{id}`` edits an existing one.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.work_history import _all_entries, export_entries
from app.db import get_session
from app.models import CandidateProfile
from app.services.openrouter import OpenRouterError, OpenRouterService, get_openrouter

router = APIRouter()


class CandidateProfileCreate(BaseModel):
    content: str = ""


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

@router.post("/", response_model=CandidateProfileOut, status_code=status.HTTP_201_CREATED)
def create_profile(
    payload: CandidateProfileCreate,
    session: Annotated[Session, Depends(get_session)],
) -> CandidateProfile:
    """Create a new profile
    """

    profile = CandidateProfile(content=payload.content)
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile

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


PROFILE_SYSTEM_PROMPT = (
    "You are an expert technical recruiter. You write candidate profiles based on the provided job history "
    "that reflects the strengths, skills and experience of the individual."
)

PROFILE_PROMPT = """\
Below is the candidate's full work history as JSON (newest position first; a null date_end
means a current position).

Write a comprehensive candidate profile in plain prose (no markdown headings).
Cover:

- total years of experience and the overall career trajectory;
- seniority level and the kinds of roles held (engineer, lead, architect, ...);
- the technology stack, grouped by how deep and how recent the experience is;
- domains and industries worked in, and the type of companies (startup, enterprise, ...);
- locations and any indication of remote or on-site work;
- notable responsibilities, achievements and areas of strength;
- sensible directions for a career growth, or next steps given the experience from the work history

Do not invent facts that are not supported by the work history.

Work history:
{work_history}
"""


def _work_history_id(session: Session) -> str | None:
    """Stable hash of the ``updated_at`` of every work history entry; ``None`` when the
    table is empty. Any edit to the work history yields a different id."""
    entries = _all_entries(session)
    if not entries:
        return None
    stamps = sorted(e.updated_at.isoformat() for e in entries)
    return hashlib.sha256("\n".join(stamps).encode()).hexdigest()

@router.post("/generate", response_model=CandidateProfileOut, status_code=status.HTTP_201_CREATED)
def generate_profile(
    session: Annotated[Session, Depends(get_session)],
    ai_service: Annotated[OpenRouterService, Depends(get_openrouter)],
) -> CandidateProfile:
    """Generate a new profile from the work history via OpenRouter.

    Fails with 400 when there is no work history, and with 409 when the latest profile was
    already generated from the current work history (same ``work_history_id``).
    """
    work_history_id = _work_history_id(session)
    if work_history_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "missing work history")

    work_history = [e.model_dump() for e in export_entries(session)]
    prompt = PROFILE_PROMPT.format(work_history=json.dumps(work_history, indent=2))
    try:
        result = ai_service.chat(
            prompt, system=PROFILE_SYSTEM_PROMPT, source="candidate_profile.create"
        )
    except OpenRouterError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    content = result.text.strip()
    if not content:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "empty response from OpenRouter")

    profile = CandidateProfile(content=content, work_history_id=work_history_id)
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile
