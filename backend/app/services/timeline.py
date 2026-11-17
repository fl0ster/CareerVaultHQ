"""The Timeline: an append-only log of things that happened, plus a read cursor.

Producers call :func:`record_event` (or one of the typed helpers below) inside their own
transaction; nothing here commits except :func:`mark_read`. To add a new kind of event,
pick a ``type`` string, write a helper that snapshots what the UI needs into ``payload``
and add a renderer for it in ``frontend/src/timeline``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    Job,
    JobEvaluation,
    JobParseResult,
    ScrapeRun,
    ScrapeSource,
    TimelineEvent,
    TimelineState,
)

STATE_ID = 1


def record_event(
    session: Session,
    type: str,
    *,
    job_id: int | None = None,
    scrape_run_id: int | None = None,
    source_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> TimelineEvent:
    """Add a timeline event to ``session`` (the caller commits)."""
    event = TimelineEvent(
        type=type,
        job_id=job_id,
        scrape_run_id=scrape_run_id,
        source_id=source_id,
        payload=payload or {},
    )
    session.add(event)
    return event


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def record_scrape_run(session: Session, run: ScrapeRun) -> TimelineEvent:
    """Snapshot a finished (or failed) scrape run."""
    source: ScrapeSource | None = run.source
    return record_event(
        session,
        TimelineEvent.TYPE_SCRAPE_RUN,
        scrape_run_id=run.id,
        source_id=run.source_id,
        payload={
            "status": run.status,
            "source_key": source.key if source else None,
            "source_name": source.name if source else None,
            "scraped": run.scraped_count or 0,
            "new": run.new_count or 0,
            "duplicates": run.duplicate_count or 0,
            "failed_sources": run.failed_sources.split(",") if run.failed_sources else [],
            "error": run.error,
            "started_at": _iso(run.started_at),
            "finished_at": _iso(run.finished_at),
        },
    )


def record_job_evaluated(
    session: Session, parsed: JobParseResult, evaluation: JobEvaluation
) -> TimelineEvent | None:
    """Snapshot a job's first evaluation. Re-scores (e.g. after a new candidate profile)
    return ``None`` without adding anything, so they do not flood the timeline."""
    exists = session.scalar(
        select(TimelineEvent.id)
        .where(
            TimelineEvent.type == TimelineEvent.TYPE_JOB_EVALUATED,
            TimelineEvent.job_id == parsed.job_id,
        )
        .limit(1)
    )
    if exists is not None:
        return None
    job: Job = parsed.job
    return record_event(
        session,
        TimelineEvent.TYPE_JOB_EVALUATED,
        job_id=parsed.job_id,
        scrape_run_id=job.scrape_run_id,
        source_id=job.source_id,
        payload={
            "title": parsed.title,
            "company_id": parsed.company_id,
            "company_name": parsed.company.name if parsed.company else None,
            "source_name": job.source.name if job.source else None,
            "link": job.link,
            "match_probability": evaluation.match_probability,
        },
    )


# --- read cursor ----------------------------------------------------------------------


def _state(session: Session) -> TimelineState:
    state = session.get(TimelineState, STATE_ID)
    if state is None:
        state = TimelineState(id=STATE_ID, last_read_event_id=0)
        session.add(state)
        session.flush()
    return state


def latest_event_id(session: Session) -> int:
    return session.scalar(select(func.max(TimelineEvent.id))) or 0


def last_read_event_id(session: Session) -> int:
    state = session.get(TimelineState, STATE_ID)
    return state.last_read_event_id if state is not None else 0


def mark_read(session: Session, event_id: int) -> None:
    """Move the read cursor forward to ``event_id`` (never backwards, never past the
    newest event) and commit."""
    state = _state(session)
    target = min(event_id, latest_event_id(session))
    if target > state.last_read_event_id:
        state.last_read_event_id = target
    session.commit()


def is_relevant(event: TimelineEvent, threshold: float) -> bool | None:
    """Whether a job event is at or above the relevance threshold; ``None`` for events
    that carry no score."""
    probability = (event.payload or {}).get("match_probability")
    if probability is None:
        return None
    return probability >= threshold


@dataclass
class TimelineStatus:
    latest_id: int
    last_read_id: int
    unread: int
    unread_relevant: int


def status(session: Session) -> TimelineStatus:
    threshold = get_settings().relevant_job_threshold
    last_read = last_read_event_id(session)
    unread = session.scalar(
        select(func.count()).select_from(TimelineEvent).where(TimelineEvent.id > last_read)
    )
    unread_jobs = session.scalars(
        select(TimelineEvent).where(
            TimelineEvent.id > last_read,
            TimelineEvent.type == TimelineEvent.TYPE_JOB_EVALUATED,
        )
    ).all()
    return TimelineStatus(
        latest_id=latest_event_id(session),
        last_read_id=last_read,
        unread=unread or 0,
        unread_relevant=sum(1 for e in unread_jobs if is_relevant(e, threshold)),
    )


# --- paging ---------------------------------------------------------------------------


@dataclass
class EventPage:
    events: list[TimelineEvent]
    has_older: bool
    has_newer: bool


def _older(session: Session, before_id: int, limit: int) -> list[TimelineEvent]:
    rows = session.scalars(
        select(TimelineEvent)
        .where(TimelineEvent.id < before_id)
        .order_by(TimelineEvent.id.desc())
        .limit(limit)
    ).all()
    return list(reversed(rows))


def _newer(session: Session, after_id: int, limit: int) -> list[TimelineEvent]:
    return list(
        session.scalars(
            select(TimelineEvent)
            .where(TimelineEvent.id > after_id)
            .order_by(TimelineEvent.id)
            .limit(limit)
        ).all()
    )


def _exists(session: Session, where) -> bool:
    return session.scalar(select(TimelineEvent.id).where(where).limit(1)) is not None


def page(
    session: Session,
    *,
    after_id: int | None = None,
    before_id: int | None = None,
    around_id: int | None = None,
    limit: int = 50,
    context: int = 20,
) -> EventPage:
    """Events in ascending ``id`` order.

    * ``after_id``: up to ``limit`` events newer than it.
    * ``before_id``: up to ``limit`` events older than it.
    * ``around_id``: up to ``context`` events at or before it and ``limit`` after it (the
      initial load around the read cursor).
    * none: the newest ``limit`` events.
    """
    if after_id is not None:
        events = _newer(session, after_id, limit)
    elif before_id is not None:
        events = _older(session, before_id, limit)
    elif around_id is not None:
        events = _older(session, around_id + 1, context) + _newer(session, around_id, limit)
    else:
        events = _older(session, latest_event_id(session) + 1, limit)

    if not events:
        # Nothing in the requested direction; the other direction may still hold events.
        if after_id is not None:
            return EventPage([], _exists(session, TimelineEvent.id <= after_id), False)
        if before_id is not None:
            return EventPage([], False, _exists(session, TimelineEvent.id >= before_id))
        return EventPage([], False, False)
    return EventPage(
        events,
        has_older=_exists(session, TimelineEvent.id < events[0].id),
        has_newer=_exists(session, TimelineEvent.id > events[-1].id),
    )


# --- retention ------------------------------------------------------------------------


def prune_read_events(session: Session, older_than: datetime) -> int:
    """Delete already-read events older than ``older_than``; returns how many."""
    last_read = last_read_event_id(session)
    deleted = session.execute(
        delete(TimelineEvent)
        .where(TimelineEvent.occurred_at < older_than, TimelineEvent.id <= last_read)
        .execution_options(synchronize_session=False)
    ).rowcount
    session.commit()
    return deleted
