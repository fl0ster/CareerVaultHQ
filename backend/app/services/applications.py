"""Helpers shared by the applications API."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Application,
    ApplicationEvent,
    ApplicationStatus,
    JobDecision,
    JobParseResult,
    WorkHistoryEntry,
)


def set_job_decision(session: Session, job_parse_result_id: int, decision: str) -> JobDecision:
    """Record (or overwrite) the user's decision about a parsed job. Not committed."""
    row = session.scalar(select(JobDecision).where(JobDecision.job_parse_result_id == job_parse_result_id))
    if row is None:
        row = JobDecision(job_parse_result_id=job_parse_result_id, decision=decision)
        session.add(row)
    else:
        row.decision = decision
    return row


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


INTERVIEW_STATUS = "INTERVIEW"
"""State of interview rounds; planned rounds always have it."""
INITIAL_ONLY_STATUS = "SHORTLISTED"
"""Recorded only when the application is created: it cannot be added, removed or switched
to/from afterwards (its note and date can still be edited)."""
APPLIED_STATUS = "APPLIED"
"""Recorded at most once, and only straight after ``SHORTLISTED`` (its current state)."""
REJECTED_STATUS = "REJECTED"
CLOSED_STATUS = "CLOSED"
"""The recruitment was paused, closed or cancelled through no fault of the candidate."""
OFFER_STATUS = "OFFER"
ACCEPTED_STATUS = "ACCEPTED"
"""The offer was accepted. Only recorded by ``accept_offer`` (which also adds the position to
the work history), never as a plain state change."""
FINAL_STATUSES = frozenset({OFFER_STATUS, ACCEPTED_STATUS, REJECTED_STATUS, CLOSED_STATUS})
"""Terminal states: once one is current, no further state can be added (removing it reopens
the application)."""


class EventRejected(Exception):
    """A state change that breaks the application rules. ``kind`` is ``"invalid"`` (the
    request itself is wrong; HTTP 422) or ``"conflict"`` (not allowed in the application's
    current state; HTTP 409)."""

    def __init__(self, message: str, kind: str = "conflict") -> None:
        super().__init__(message)
        self.kind = kind


def status_by_key(session: Session, key: str) -> ApplicationStatus:
    """The ``ApplicationStatus`` row for ``key`` (case-insensitive); ``EventRejected``
    (``invalid``) when there is none."""
    ensure_statuses(session)
    row = session.scalar(select(ApplicationStatus).where(ApplicationStatus.key == key.upper()))
    if row is None:
        raise EventRejected(f"unknown status {key!r}", "invalid")
    return row


def reject_initial_only(key: str) -> None:
    if key.upper() == INITIAL_ONLY_STATUS:
        raise EventRejected(f"{INITIAL_ONLY_STATUS} is only set when the application is created", "invalid")


def reject_accepted(key: str) -> None:
    if key.upper() == ACCEPTED_STATUS:
        raise EventRejected(f"{ACCEPTED_STATUS} is only set by accepting the offer", "invalid")


def reject_if_final(application: Application) -> None:
    current = application.current_event
    if current is not None and current.status.key in FINAL_STATUSES:
        raise EventRejected(f"application is {current.status.key}; remove that state to record new ones")


def reject_out_of_order(
    application: Application,
    key: str,
    when: datetime | None,
    *,
    event: ApplicationEvent | None = None,
) -> None:
    """``EventRejected`` (``invalid``) when recording ``key`` at ``when`` (or moving
    ``event`` there) would date a state before ``APPLIED``, or ``APPLIED`` after a later
    state. ``SHORTLISTED`` and planned rounds are not checked; neither is an unset time."""
    key = key.upper()
    if when is None or key == INITIAL_ONLY_STATUS:
        return
    when = _minute(when)
    dated = [e for e in application.history if e is not event and e.occurred_at is not None]
    if key in (INTERVIEW_STATUS, APPLIED_STATUS):
        shortlisted = next((e for e in dated if e.status.key == INITIAL_ONLY_STATUS), None)
        if shortlisted is not None and when < _minute(shortlisted.occurred_at):
            raise EventRejected(f"{key} cannot be dated before {INITIAL_ONLY_STATUS}", "invalid")
    others = [e for e in dated if e.status.key != INITIAL_ONLY_STATUS]
    if key == APPLIED_STATUS:
        if any(_minute(e.occurred_at) < when for e in others):
            raise EventRejected(f"{APPLIED_STATUS} cannot be dated after a later state", "invalid")
        return
    applied = next((e for e in others if e.status.key == APPLIED_STATUS), None)
    if applied is not None and when < _minute(applied.occurred_at):
        raise EventRejected(f"a state cannot be dated before {APPLIED_STATUS}", "invalid")


def is_open(application: Application) -> bool:
    """The application has been sent (``APPLIED`` recorded) and has no final state yet."""
    current = application.current_event
    if current is None or current.status.key in FINAL_STATUSES:
        return False
    return any(e.status.key == APPLIED_STATUS for e in application.history)


def record_event(
    session: Session,
    application: Application,
    status_key: str,
    *,
    note: str = "",
    occurred_at: datetime | None = None,
    source: str = ApplicationEvent.SOURCE_MANUAL,
    source_ref: str | None = None,
) -> ApplicationEvent:
    """Record a state change on ``application`` following the application rules (see
    ``app.api.routes.applications``); ``EventRejected`` when they forbid it. Recording
    ``INTERVIEW`` holds the first planned round instead of adding one. Not committed."""
    reject_initial_only(status_key)
    reject_accepted(status_key)
    reject_if_final(application)
    key = status_key.upper()
    if key == APPLIED_STATUS:
        current = application.current_event
        if any(e.status.key == APPLIED_STATUS for e in application.events):
            raise EventRejected(f"application is already {APPLIED_STATUS}")
        if current is None or current.status.key != INITIAL_ONLY_STATUS:
            raise EventRejected(f"{APPLIED_STATUS} can only follow {INITIAL_ONLY_STATUS}")
    plan = application.plan
    if occurred_at is not None:
        reject_out_of_order(application, key, occurred_at)
    if key == INTERVIEW_STATUS and plan:
        # Hold the next planned round instead of adding a new one.
        event = plan[0]
        event.occurred_at = occurred_at or held_at(application, event)
        event.planned = False
        event.note = note or event.note
        event.source = source
        event.source_ref = source_ref
        session.flush()
        session.expire(application, ["events"])
        return event
    event = ApplicationEvent(
        status=status_by_key(session, key),
        note=note,
        source=source,
        source_ref=source_ref,
        occurred_at=occurred_at or datetime.now(UTC),
    )
    # Appended (rather than only added to the session) so ``application.events`` and
    # ``current_event`` stay right for callers that keep using the object.
    application.events.append(event)
    session.flush()
    session.expire(application, ["events"])
    return event


def accept_offer(session: Session, application: Application, start_date: date | None = None) -> WorkHistoryEntry:
    """Accept the application's offer: record ``ACCEPTED`` and add the position to the work
    history, starting on ``start_date`` (or the application's stored ``start_date``, which is
    updated to the one used), seeded with the job's title, company and technologies and
    marked ``PREFILL_QUEUED`` for ``app.tasks.work_history.prefill``. ``EventRejected``
    unless the current state is ``OFFER`` (``conflict``) or when no start date is known
    (``invalid``). Not committed."""
    current = application.current_event
    if current is None or current.status.key != OFFER_STATUS:
        raise EventRejected(f"only an application in {OFFER_STATUS} can be accepted")
    if application.work_entry is not None:
        raise EventRejected("the offer was already added to the work history")
    start = start_date or application.start_date
    if start is None:
        raise EventRejected("a start date is required to accept the offer", "invalid")
    application.start_date = start

    accepted = status_by_key(session, ACCEPTED_STATUS)
    # Now, but never before the offer (which may have been dated ahead), so it is current.
    when = max(datetime.now(UTC), _naive(current.occurred_at).replace(tzinfo=UTC) + timedelta(minutes=1))
    application.events.append(ApplicationEvent(status=accepted, occurred_at=when))
    parsed = application.job_parse_result
    entry = WorkHistoryEntry(
        date_start=start,
        employer=(parsed.company.name if parsed.company is not None else "") or "Unknown employer",
        role=seeded_role(parsed),
        tech=seeded_tech(parsed),
        application=application,
        prefill_state=WorkHistoryEntry.PREFILL_QUEUED,
    )
    session.add(entry)
    session.flush()
    session.expire(application, ["events"])
    return entry


def seeded_role(parsed: JobParseResult) -> str:
    """The role a work-history entry created from ``parsed`` starts with: the job title."""
    return (parsed.title or "").strip()[:256] or "Unknown role"


def seeded_tech(parsed: JobParseResult) -> list[str]:
    """Technology names extracted from the job description, de-duplicated, in order."""
    names: list[str] = []
    for item in parsed.technologies or []:
        name = str(item.get("name") or "").strip() if isinstance(item, dict) else ""
        if name and name.casefold() not in {n.casefold() for n in names}:
            names.append(name)
    return names


def undo_accept(session: Session, application: Application) -> None:
    """Drop the work-history entry created by accepting the offer (when its ``ACCEPTED``
    state is removed). Not committed."""
    entry = application.work_entry
    if entry is not None:
        application.work_entry = None
        session.delete(entry)


def _naive(moment: datetime) -> datetime:
    return moment.replace(tzinfo=None) if moment.tzinfo else moment


def _minute(moment: datetime) -> datetime:
    """Naive, to the minute: the precision the UI's date inputs have."""
    return _naive(moment).replace(second=0, microsecond=0)


def held_at(application: Application, event: ApplicationEvent) -> datetime:
    """When a planned round being held took place: its scheduled time when that is after
    every state already recorded (so it never lands before ``APPLIED``), otherwise now."""
    scheduled = event.occurred_at
    if scheduled is not None:
        latest = max(
            (_naive(e.occurred_at) for e in application.history if e.occurred_at),
            default=None,
        )
        if latest is None or _naive(scheduled) > latest:
            return scheduled
    return datetime.now(UTC)


def held_rounds(application: Application) -> list[ApplicationEvent]:
    """Interview rounds that already took place."""
    return [e for e in application.history if e.status.key == INTERVIEW_STATUS]


def set_interview_rounds(session: Session, application: Application, rounds: int, interview: ApplicationStatus) -> None:
    """Add blank planned rounds at the end, or drop them from the end, so the application has
    ``rounds`` interview rounds (held + planned; at least the held ones). Not committed."""
    plan = application.plan
    wanted = max(rounds - len(held_rounds(application)), 0)
    for event in plan[wanted:]:
        application.events.remove(event)
        session.delete(event)
    for _ in range(wanted - len(plan)):
        application.events.append(ApplicationEvent(status=interview, planned=True, occurred_at=None))


def plan_parsed_rounds(session: Session, application: Application, parsed: JobParseResult) -> None:
    """Append the interview rounds extracted from the job description
    (``parsed.interview_steps``) to ``application`` as planned ``INTERVIEW`` events, in
    round order, with their titles and durations. No-op when none were extracted. Not
    committed."""
    steps = sorted(parsed.interview_steps or [], key=lambda s: s.get("number") or 0)
    if not steps:
        return
    interview = status_by_key(session, INTERVIEW_STATUS)
    for step in steps:
        application.events.append(
            ApplicationEvent(
                status=interview,
                planned=True,
                occurred_at=None,
                title=str(step.get("title") or "")[:128],
                duration_minutes=step.get("duration_minutes"),
            )
        )


def application_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Application)) or 0


def current_stage_counts(session: Session) -> dict[str, int]:
    """``{status key: applications currently in it}``, counted in SQL.

    An application's current state is its latest held (not planned) event, ordered like
    ``Application.history``: by ``occurred_at`` (undated last), then by id.
    """
    rank = (
        func.row_number()
        .over(
            partition_by=ApplicationEvent.application_id,
            order_by=(
                ApplicationEvent.occurred_at.is_(None).desc(),
                ApplicationEvent.occurred_at.desc(),
                ApplicationEvent.id.desc(),
            ),
        )
        .label("rank")
    )
    latest = select(ApplicationEvent.status_id, rank).where(ApplicationEvent.planned.is_(False)).subquery()
    rows = session.execute(
        select(ApplicationStatus.key, func.count())
        .join(latest, latest.c.status_id == ApplicationStatus.id)
        .where(latest.c.rank == 1)
        .group_by(ApplicationStatus.key)
    ).all()
    return dict(rows)
