"""Candidate details: the personal data printed on a generated CV (name, contact lines,
education, certifications, languages and the consent clause).

A singleton: ``GET`` returns the row (``null`` until it is saved once) and ``PUT`` creates
or replaces it in full.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import CandidateDetails
from app.schemas.candidate_details import CandidateDetailsIn

router = APIRouter()


class CandidateDetailsOut(CandidateDetailsIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


def _current(session: Session) -> CandidateDetails | None:
    return session.scalar(select(CandidateDetails).order_by(CandidateDetails.id.desc()).limit(1))


@router.get("", response_model=CandidateDetailsOut | None)
def get_details(session: Annotated[Session, Depends(get_session)]) -> CandidateDetails | None:
    """The saved details, or ``null`` when none were saved yet."""
    return _current(session)


@router.put("", response_model=CandidateDetailsOut)
def put_details(payload: CandidateDetailsIn, session: Annotated[Session, Depends(get_session)]) -> CandidateDetails:
    """Create or replace the details."""
    details = _current(session)
    if details is None:
        details = CandidateDetails()
        session.add(details)
    for field, value in payload.cleaned().items():
        setattr(details, field, value)
    session.commit()
    session.refresh(details)
    return details
