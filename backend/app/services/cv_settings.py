"""CV settings (``cv_settings``, a single row): the consent clause printed on the CV and
overrides of the timeline rules, whose defaults are the ``cv_*`` values of ``Settings``."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import CandidateDetails, CVSettings

SETTINGS_ID = 1

DEFAULT_CONSENT = (
    "I consent to the processing of my personal data for recruitment purposes in accordance with GDPR "
    "(Regulation (EU) 2016/679)."
)

TIMELINE_FIELDS = ("max_entries", "min_entries", "high_relevance", "irrelevant_relevance", "min_months")
"""Timeline rules; each overrides ``Settings.cv_<name>`` when set."""


def get_cv_settings(session: Session) -> CVSettings:
    """The settings row, created on first use. Its consent clause starts as the one saved
    with the personal details (where it used to live), or the default clause."""
    row = session.get(CVSettings, SETTINGS_ID)
    if row is None:
        legacy = session.scalar(select(CandidateDetails).order_by(CandidateDetails.id.desc()).limit(1))
        row = CVSettings(id=SETTINGS_ID, consent_text=legacy.consent_text if legacy else DEFAULT_CONSENT)
        session.add(row)
        session.commit()
    return row


def timeline_defaults(settings: Settings) -> dict[str, Any]:
    return {name: getattr(settings, f"cv_{name}") for name in TIMELINE_FIELDS}


def timeline_rules(row: CVSettings, settings: Settings) -> dict[str, Any]:
    """The rules in effect: each override, or the default where none is set."""
    defaults = timeline_defaults(settings)
    return {name: defaults[name] if getattr(row, name) is None else getattr(row, name) for name in TIMELINE_FIELDS}
