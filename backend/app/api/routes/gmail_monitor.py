"""Gmail rejection monitor (see ``app.tasks.gmail.rejections``).

* ``GET``/``PATCH /api/gmail-monitor/settings`` read and edit the configuration; the shared
  secret is never returned, only ``secret_hint``. ``POST /settings/rotate-secret`` replaces
  it (the script must be pasted again afterwards).
* ``GET /api/gmail-monitor/apps-script`` returns the Apps Script source with the secret
  filled in, ready to paste into script.google.com.
* ``POST /api/gmail-monitor/test`` calls the deployed script and reports which account it
  runs as.
* ``POST /api/gmail-monitor/run`` queues a check now (``202``; returns the running job when
  one is already queued/running); poll ``GET /api/gmail-monitor/jobs/{job_id}``.
* ``GET /api/gmail-monitor/mails`` lists the mails looked at, newest first, with what was
  done about each.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, field_validator
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import Settings, get_settings
from app.db import get_session
from app.integrations.gmail import (
    LABEL_PATTERN,
    MAX_LOOKBACK_DAYS,
    SCRIPT_URL_PATTERN,
    AppsScriptError,
    script_source,
)
from app.models import Application, GmailInterviewMail, GmailMonitorSettings, GmailProcessedMail, JobParseResult
from app.queue import get_queue
from app.scheduler.gmail import GMAIL_JOB_ID, MIN_INTERVAL_SECONDS, enqueue_gmail_check
from app.services.gmail_monitor import (
    client_for,
    get_monitor_settings,
    is_configured,
    new_secret,
    same_address,
)

router = APIRouter()


class MonitorSettingsOut(BaseModel):
    enabled: bool
    configured: bool
    """``email`` and ``script_url`` are both set."""
    email: str
    script_url: str
    secret_hint: str
    """Last characters of the shared secret, to tell whether the deployed script is current."""
    label: str
    interview_label: str
    """Gmail label added to the mails whose interview steps were stored."""
    interval_seconds: int
    lookback_days: int
    threshold: float
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_status: str | None
    last_error: str | None
    last_summary: dict[str, Any] | None
    job_id: str
    """Fixed RQ id of the check (scheduled and manual runs share it)."""


class MonitorSettingsUpdate(BaseModel):
    enabled: bool | None = None
    email: str | None = Field(default=None, max_length=320)
    script_url: str | None = Field(default=None, max_length=1024)
    label: str | None = Field(default=None, pattern=LABEL_PATTERN)
    """Letters, digits, spaces and ``_ . / -`` only (what the Apps Script accepts)."""
    interview_label: str | None = Field(default=None, pattern=LABEL_PATTERN)
    interval_seconds: int | None = Field(default=None, ge=MIN_INTERVAL_SECONDS, le=7 * 24 * 3600)
    lookback_days: int | None = Field(default=None, ge=1, le=MAX_LOOKBACK_DAYS)
    threshold: float | None = Field(default=None, ge=0.5, le=1.0)

    @field_validator("email", "script_url", "label", "interview_label")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        if value and "@" not in value:
            raise ValueError("not an e-mail address")
        return value

    @field_validator("script_url")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        if value and re.fullmatch(SCRIPT_URL_PATTERN, value) is None:
            raise ValueError("the web app URL must look like https://script.google.com/macros/s/<id>/exec")
        return value


class TestResult(BaseModel):
    ok: bool
    email: str | None = None
    """Account the deployed script runs as."""
    matches_configured: bool = False
    error: str | None = None


class MonitorJobInfo(BaseModel):
    job_id: str
    status: str
    enqueued_at: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class InterviewCheckOut(BaseModel):
    """Result of the interview-steps check on a mail (``gmail_interview_mails``)."""

    outcome: str
    present_probability: float | None
    """Probability that the mail describes the interview process."""
    faithful_probability: float | None
    steps: list[dict[str, Any]] | None
    company: str | None
    role: str | None
    application_id: int | None
    application_title: str | None = None
    error: str | None


class ProcessedMailOut(BaseModel):
    id: int
    message_id: str
    subject: str
    sender: str
    received_at: datetime | None
    outcome: str
    probability: float | None
    company: str | None
    role: str | None
    application_id: int | None
    application_title: str | None = None
    error: str | None
    created_at: datetime
    interview: InterviewCheckOut | None = None
    """``None`` when the interview-steps check did not look at the mail (rejections, and
    mails whose check is to be retried)."""


def _settings_out(row: GmailMonitorSettings) -> MonitorSettingsOut:
    return MonitorSettingsOut(
        enabled=row.enabled,
        configured=is_configured(row),
        email=row.email or "",
        script_url=row.script_url or "",
        secret_hint=f"…{row.secret[-4:]}" if row.secret else "",
        label=row.label,
        interview_label=row.interview_label,
        interval_seconds=row.interval_seconds,
        lookback_days=row.lookback_days,
        threshold=row.threshold,
        next_run_at=row.next_run_at,
        last_run_at=row.last_run_at,
        last_status=row.last_status,
        last_error=row.last_error,
        last_summary=row.last_summary,
        job_id=GMAIL_JOB_ID,
    )


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _job_info(job: Job) -> MonitorJobInfo:
    job_status = job.get_status(refresh=False)
    info = MonitorJobInfo(
        job_id=job.id,
        status=job_status,
        enqueued_at=_iso(job.enqueued_at),
        started_at=_iso(job.started_at),
        ended_at=_iso(job.ended_at),
    )
    if job_status == "finished":
        info.result = job.return_value()
    elif job_status == "failed":
        latest = job.latest_result()
        if latest is not None and latest.exc_string:
            info.error = latest.exc_string.strip().splitlines()[-1]
    return info


@router.get("/settings", response_model=MonitorSettingsOut)
def read_settings(session: Annotated[Session, Depends(get_session)]) -> MonitorSettingsOut:
    return _settings_out(get_monitor_settings(session))


@router.patch("/settings", response_model=MonitorSettingsOut)
def update_settings(payload: MonitorSettingsUpdate, session: Annotated[Session, Depends(get_session)]) -> MonitorSettingsOut:
    """Change the given fields. Changing the interval or turning the monitor on makes the
    scheduler run a check at its next tick."""
    row = get_monitor_settings(session)
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    if changes.get("interval_seconds", row.interval_seconds) != row.interval_seconds or (
        changes.get("enabled") and not row.enabled
    ):
        row.next_run_at = None
    for name, value in changes.items():
        setattr(row, name, value)
    session.commit()
    return _settings_out(row)


@router.post("/settings/rotate-secret", response_model=MonitorSettingsOut)
def rotate_secret(session: Annotated[Session, Depends(get_session)]) -> MonitorSettingsOut:
    """Replace the shared secret; the deployed script stops working until it is updated."""
    row = get_monitor_settings(session)
    row.secret = new_secret()
    session.commit()
    return _settings_out(row)


@router.get("/apps-script")
def apps_script(session: Annotated[Session, Depends(get_session)]) -> Response:
    """The Apps Script source to paste into script.google.com (contains the secret)."""
    row = get_monitor_settings(session)
    return Response(
        script_source(row.secret),
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/test", response_model=TestResult)
def test_connection(session: Annotated[Session, Depends(get_session)]) -> TestResult:
    """Call the deployed script; ``ok`` only when it answers and runs as the configured
    account."""
    row = get_monitor_settings(session)
    try:
        email = client_for(row).ping()
    except AppsScriptError as exc:
        return TestResult(ok=False, error=str(exc))
    matches = bool(row.email) and same_address(email, row.email)
    error = None
    if not matches:
        error = f"the script runs as {email or 'an unknown account'}, not {row.email or 'the configured address (none set)'}"
    return TestResult(ok=matches, email=email, matches_configured=matches, error=error)


@router.post("/run", response_model=MonitorJobInfo, status_code=status.HTTP_202_ACCEPTED)
def run_now(
    session: Annotated[Session, Depends(get_session)],
    queue: Annotated[Queue, Depends(get_queue)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MonitorJobInfo:
    """Queue a check now (also when the monitor is disabled); ``400`` when not configured."""
    row = get_monitor_settings(session)
    if not is_configured(row):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "set the monitored e-mail and the Apps Script web app URL first",
        )
    return _job_info(enqueue_gmail_check(queue, settings, scheduled=False))


@router.get("/jobs/{job_id}", response_model=MonitorJobInfo)
def job_status(job_id: str, queue: Annotated[Queue, Depends(get_queue)]) -> MonitorJobInfo:
    try:
        job = Job.fetch(job_id, connection=queue.connection)
    except NoSuchJobError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown job") from exc
    return _job_info(job)


@router.get("/mails", response_model=list[ProcessedMailOut])
def list_mails(
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    outcome: str | None = None,
) -> list[ProcessedMailOut]:
    """Mails the monitor looked at, newest first; ``outcome`` filters by what was done."""
    stmt = select(GmailProcessedMail).order_by(GmailProcessedMail.id.desc()).limit(limit)
    if outcome:
        stmt = stmt.where(GmailProcessedMail.outcome == outcome)
    rows = session.scalars(stmt).all()
    interviews = {
        i.message_id: i
        for i in session.scalars(
            select(GmailInterviewMail).where(GmailInterviewMail.message_id.in_([r.message_id for r in rows]))
        )
    }
    app_ids = {r.application_id for r in [*rows, *interviews.values()] if r.application_id is not None}
    titles: dict[int, str] = {}
    if app_ids:
        for application in session.scalars(
            select(Application)
            .where(Application.id.in_(app_ids))
            .options(joinedload(Application.job_parse_result).joinedload(JobParseResult.company))
        ):
            parsed = application.job_parse_result
            company = parsed.company.name if parsed.company is not None else None
            titles[application.id] = " @ ".join(t for t in (parsed.title, company) if t)
    return [
        ProcessedMailOut(
            id=r.id,
            message_id=r.message_id,
            subject=r.subject,
            sender=r.sender,
            received_at=r.received_at,
            outcome=r.outcome,
            probability=r.probability,
            company=r.company,
            role=r.role,
            application_id=r.application_id,
            application_title=titles.get(r.application_id) if r.application_id else None,
            error=r.error,
            created_at=r.created_at,
            interview=_interview_out(interviews.get(r.message_id), titles),
        )
        for r in rows
    ]


def _interview_out(row: GmailInterviewMail | None, titles: dict[int, str]) -> InterviewCheckOut | None:
    if row is None:
        return None
    return InterviewCheckOut(
        outcome=row.outcome,
        present_probability=row.present_probability,
        faithful_probability=row.faithful_probability,
        steps=row.steps,
        company=row.company,
        role=row.role,
        application_id=row.application_id,
        application_title=titles.get(row.application_id) if row.application_id else None,
        error=row.error,
    )
