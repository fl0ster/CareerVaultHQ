"""Candidate details: the personal data printed on a generated CV (name, contact lines,
education, certifications, languages and the consent clause).

A singleton: ``GET`` returns the row (``null`` until it is saved once) and ``PUT`` creates
or replaces it in full.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import CandidateDetails

router = APIRouter()


class EducationEntry(BaseModel):
    degree: str = Field(default="", max_length=256)
    institution: str = Field(default="", max_length=256)
    date_start: str = Field(default="", max_length=64)
    """Free text, printed verbatim (``Oct 2012``)."""
    date_end: str = Field(default="", max_length=64)
    note: str = Field(default="", max_length=1024)


class LanguageEntry(BaseModel):
    language: str = Field(default="", max_length=64)
    level: str = Field(default="", max_length=128)


class CandidateDetailsIn(BaseModel):
    first_name: str = Field(default="", max_length=128)
    last_name: str = Field(default="", max_length=128)
    email: str = Field(default="", max_length=256)
    phone: str = Field(default="", max_length=64)
    website: str = Field(default="", max_length=512)
    github: str = Field(default="", max_length=512)
    linkedin: str = Field(default="", max_length=512)
    location: str = Field(default="", max_length=256)
    education: list[EducationEntry] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    languages: list[LanguageEntry] = Field(default_factory=list)
    consent_text: str = ""

    def cleaned(self) -> dict:
        """Trimmed values; blank education/language rows and certifications are dropped."""
        data = self.model_dump()
        for key, value in data.items():
            if isinstance(value, str):
                data[key] = value.strip()
        data["education"] = [
            {k: v.strip() for k, v in e.items()} for e in data["education"] if any(v.strip() for v in e.values())
        ]
        data["languages"] = [
            {k: v.strip() for k, v in lang.items()} for lang in data["languages"] if lang["language"].strip()
        ]
        data["certifications"] = [c.strip() for c in data["certifications"] if c.strip()]
        return data


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
