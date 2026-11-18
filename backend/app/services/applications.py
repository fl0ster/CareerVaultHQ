"""Helpers shared by the applications API."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApplicationStatus


def ensure_statuses(session: Session) -> None:
    """Create the default ``ApplicationStatus`` rows that do not exist yet (idempotent;
    existing rows, including edited labels and custom statuses, are left alone)."""
    existing = set(session.scalars(select(ApplicationStatus.key)))
    missing = [
        ApplicationStatus(key=key, label=label, position=i * 10, next_key=next_key or None)
        for i, (key, label, next_key) in enumerate(ApplicationStatus.DEFAULTS)
        if key not in existing
    ]
    if missing:
        session.add_all(missing)
        session.commit()
