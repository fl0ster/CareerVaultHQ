"""CV settings (``cv_settings``, a single row): the consent clause printed on the CV and
overrides of the timeline rules, whose defaults are the ``cv_*`` values of ``Settings``."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.models import CVSettings

SETTINGS_ID = 1

DEFAULT_CONSENT = (
    "I consent to the processing of my personal data for recruitment purposes in accordance with GDPR "
    "(Regulation (EU) 2016/679)."
)

TIMELINE_FIELDS = ("max_entries", "min_entries", "high_relevance", "irrelevant_relevance", "min_months")
"""Timeline rules; each overrides ``Settings.cv_<name>`` when set."""


def get_cv_settings(session: Session) -> CVSettings:
    """The settings row, created on first use with the default consent clause and no rule
    overrides."""
    row = session.get(CVSettings, SETTINGS_ID)
    if row is None:
        row = CVSettings(id=SETTINGS_ID, consent_text=DEFAULT_CONSENT)
        session.add(row)
        session.commit()
    return row


def timeline_defaults(settings: Settings) -> dict[str, Any]:
    return {name: getattr(settings, f"cv_{name}") for name in TIMELINE_FIELDS}


def timeline_rules(row: CVSettings, settings: Settings) -> dict[str, Any]:
    """The rules in effect: each override, or the default where none is set."""
    defaults = timeline_defaults(settings)
    return {name: defaults[name] if getattr(row, name) is None else getattr(row, name) for name in TIMELINE_FIELDS}
