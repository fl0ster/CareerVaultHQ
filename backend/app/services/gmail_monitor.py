"""Settings of the Gmail rejection monitor (``gmail_monitor_settings``, a single row)."""

from __future__ import annotations

import secrets

from sqlalchemy.orm import Session

from app.integrations.gmail import AppsScriptClient
from app.models import GmailMonitorSettings

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
            email="",
            script_url="",
            secret=new_secret(),
            label=GmailMonitorSettings.DEFAULT_LABEL,
            interval_seconds=GmailMonitorSettings.DEFAULT_INTERVAL_SECONDS,
            lookback_days=GmailMonitorSettings.DEFAULT_LOOKBACK_DAYS,
            threshold=GmailMonitorSettings.DEFAULT_THRESHOLD,
        )
        session.add(row)
        session.commit()
    return row


def is_configured(row: GmailMonitorSettings) -> bool:
    return bool(row.script_url and row.email and row.secret)


def client_for(row: GmailMonitorSettings) -> AppsScriptClient:
    return AppsScriptClient(row.script_url, row.secret)


def same_address(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()
