"""Request shape of the candidate details, shared by ``api.routes.candidate_details`` and
``tasks.cv_import``; kept outside ``app.api`` for the same reason as ``schemas.work_history``."""

from __future__ import annotations

from pydantic import BaseModel, Field

MAX_PHOTO_LENGTH = 1_000_000
"""The browser scales the picture down before saving; this only rejects runaway payloads."""
PHOTO_PATTERN = r"^(data:image/(png|jpeg|webp);base64,[A-Za-z0-9+/]+=*)?$"


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
    languages: list[LanguageEntry] = Field(default_factory=list)
    # The consent clause is a CV setting (``/api/cv-settings``), not a personal detail.

    def cleaned(self) -> dict:
        """Trimmed values; blank language rows are dropped."""
        data = self.model_dump()
        for key, value in data.items():
            if isinstance(value, str):
                data[key] = value.strip()
        data["languages"] = [
            {k: v.strip() for k, v in lang.items()} for lang in data["languages"] if lang["language"].strip()
        ]
        return data
