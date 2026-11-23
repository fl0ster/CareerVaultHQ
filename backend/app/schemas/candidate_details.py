"""Request shape of the candidate details, shared by ``api.routes.candidate_details`` and
``tasks.cv_import``; kept outside ``app.api`` for the same reason as ``schemas.work_history``."""

from __future__ import annotations

from pydantic import BaseModel, Field

MAX_PHOTO_LENGTH = 1_000_000
"""The browser scales the picture down before saving; this only rejects runaway payloads."""
PHOTO_PATTERN = r"^(data:image/(png|jpeg|webp);base64,[A-Za-z0-9+/]+=*)?$"


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
    photo: str = Field(default="", max_length=MAX_PHOTO_LENGTH, pattern=PHOTO_PATTERN)
    """Profile picture as a base64 image ``data:`` URL; blank = none."""
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
