"""Settings of the Gmail rejection monitor (``gmail_monitor_settings``, a single row)."""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.gmail import AppsScriptClient
from app.models import CandidateDetails, GmailMonitorSettings

SETTINGS_ID = 1
MAX_MESSAGES_PER_RUN = 30
"""Messages fetched from Gmail per run; the rest are picked up by the next run."""


def new_secret() -> str:
    return secrets.token_urlsafe(32)


def get_monitor_settings(session: Session) -> GmailMonitorSettings:
    """The settings row, created with defaults (and a fresh secret) on first use."""
    row = session.get(GmailMonitorSettings, SETTINGS_ID)
    if row is None:
        row = GmailMonitorSettings(
            id=SETTINGS_ID,
            enabled=False,
            script_url="",
            secret=new_secret(),
            label=GmailMonitorSettings.DEFAULT_LABEL,
            interview_label=GmailMonitorSettings.DEFAULT_INTERVIEW_LABEL,
            interval_seconds=GmailMonitorSettings.DEFAULT_INTERVAL_SECONDS,
            lookback_days=GmailMonitorSettings.DEFAULT_LOOKBACK_DAYS,
            threshold=GmailMonitorSettings.DEFAULT_THRESHOLD,
        )
        session.add(row)
        session.commit()
    return row


def monitored_email(session: Session) -> str:
    """The monitored Gmail address: the e-mail in the personal details (the one printed on
    the CV); blank when none is set."""
    email = session.scalar(select(CandidateDetails.email).order_by(CandidateDetails.id.desc()).limit(1))
    return (email or "").strip()


def is_configured(session: Session, row: GmailMonitorSettings) -> bool:
    return bool(row.script_url and row.secret and monitored_email(session))


def client_for(row: GmailMonitorSettings) -> AppsScriptClient:
    return AppsScriptClient(row.script_url, row.secret)


def same_address(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()
