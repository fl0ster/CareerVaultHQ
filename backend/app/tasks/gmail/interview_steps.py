"""Gmail interview-steps check, run by ``check_rejection_mails`` on the same mails.

For every fetched mail the rejection check classified as *not* a rejection (and not looked
at by this check before):

1. runs the interview-steps pipeline used on job descriptions
   (``app.tasks.parse.parse.extract_interview_steps``: Jev presence check, chat extraction,
   Jev faithfulness check) on the mail; no faithful steps -> the mail is left alone;
2. asks a chat model for the hiring company and the role (as the rejection check does);
3. matches them against the *unfinished* applications (no final state; unlike the rejection
   check, ``APPLIED`` need not be recorded, as the user may not have moved it yet) with the
   rejection check's matching: the company must match by name or alias and, when several
   such applications are at that company, the role must single one out;
4. when the matched job has no interview steps yet, stores the steps on its
   ``JobParseResult.interview_steps``, plans them on the application as interview rounds
   when it has no planned rounds yet, and adds ``gmail_monitor_settings.interview_label``
   to the mail. The mail's
   read state is never changed.

Every mail is recorded in ``gmail_interview_mails`` with its outcome so it is never sent to
OpenRouter twice by this check (a failing OpenRouter call is not recorded, so the mail is
retried by the next run). Mails that are rejections, or whose rejection check failed, are not
looked at.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.gmail import AppsScriptClient, AppsScriptError, GmailMessage
from app.models import Application, GmailInterviewMail, GmailMonitorSettings
from app.services.applications import FINAL_STATUSES, plan_parsed_rounds
from app.services.openrouter import OpenRouterError, OpenRouterNotConfigured, OpenRouterService
from app.tasks.gmail.rejections import (
    all_applications,
    extract_company_and_role,
    match_application,
)
from app.tasks.parse.parse import extract_interview_steps

log = logging.getLogger(__name__)


def unfinished_applications(session: Session) -> list[Application]:
    """Applications in any state but a final one (``SHORTLISTED`` included)."""
    return [
        a for a in all_applications(session) if a.current_event is None or a.current_event.status.key not in FINAL_STATUSES
    ]


SOURCE = "tasks.gmail_interview_steps"
"""``openrouter_calls.source`` label for calls made by this check."""
INTERVIEW_ABOUT = "The e-mail below is about the recruitment process of a job application the candidate sent."


@dataclass
class InterviewSummary:
    skipped: int = 0
    """Already processed in an earlier run."""
    failed: int = 0
    """OpenRouter failed; retried by the next run."""
    outcomes: dict[str, int] = field(default_factory=dict)
    applied: list[dict[str, Any]] = field(default_factory=list)

    def count(self, outcome: str) -> None:
        self.outcomes[outcome] = self.outcomes.get(outcome, 0) + 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "skipped": self.skipped,
            "failed": self.failed,
            "outcomes": dict(self.outcomes),
            "applied": list(self.applied),
        }


def _processed(session: Session, message_id: str) -> GmailInterviewMail | None:
    return session.scalar(select(GmailInterviewMail).where(GmailInterviewMail.message_id == message_id))


def _new_record(message: GmailMessage, outcome: str, **fields: Any) -> GmailInterviewMail:
    return GmailInterviewMail(
        message_id=message.id,
        thread_id=message.thread_id,
        subject=message.subject[:1024],
        sender=message.sender[:512],
        received_at=message.received_at,
        outcome=outcome,
        **fields,
    )


def _mail_text(message: GmailMessage) -> str:
    return f"From: {message.sender}\nSubject: {message.subject}\n\n{message.body}"


def _label(client: AppsScriptClient, record: GmailInterviewMail, label: str) -> None:
    """Label the mail (read state untouched); ``record.outcome`` reflects whether it worked."""
    try:
        client.label(record.message_id, label)
    except AppsScriptError as exc:
        log.warning("Labelling mail %s failed: %s", record.message_id, exc)
        record.outcome = GmailInterviewMail.OUTCOME_LABEL_FAILED
        record.error = str(exc)[:2000]
    else:
        record.outcome = GmailInterviewMail.OUTCOME_APPLIED
        record.error = None


def _register(session: Session, service: OpenRouterService, message: GmailMessage) -> GmailInterviewMail:
    """Store the mail's interview steps on the matching job (not committed); the returned
    record says what happened."""
    result = extract_interview_steps(service, _mail_text(message), source=SOURCE, private=True)
    fields: dict[str, Any] = {
        "present_probability": result.present_probability,
        "faithful_probability": result.faithful_probability,
    }
    if not result.steps:
        return _new_record(message, GmailInterviewMail.OUTCOME_NO_STEPS, **fields)
    steps = [asdict(step) for step in result.steps]
    fields["steps"] = steps

    company, role = extract_company_and_role(service, message, about=INTERVIEW_ABOUT, source=SOURCE)
    fields.update(company=company, role=role)
    if not company:
        return _new_record(message, GmailInterviewMail.OUTCOME_EXTRACTION_FAILED, **fields)
    # Match against all unfinished applications (not only those without steps), so a mail
    # about an application that has steps cannot be pinned on another one at the company.
    match = match_application(session, unfinished_applications(session), company, role)
    if match.application is None:
        return _new_record(message, match.outcome, error=match.detail or None, **fields)
    fields["application_id"] = match.application.id
    parsed = match.application.job_parse_result
    if parsed.interview_steps:
        return _new_record(message, GmailInterviewMail.OUTCOME_HAS_STEPS, **fields)
    parsed.interview_steps = steps
    if not match.application.plan:  # never add to rounds already planned (by hand or not)
        plan_parsed_rounds(session, match.application, parsed)
    return _new_record(message, GmailInterviewMail.OUTCOME_APPLIED, **fields)


def process_message(
    session: Session,
    client: AppsScriptClient,
    service: OpenRouterService,
    settings: GmailMonitorSettings,
    message: GmailMessage,
    summary: InterviewSummary,
) -> None:
    """Handle one (non-rejection) mail and record its outcome (committed)."""
    previous = _processed(session, message.id)
    if previous is not None:
        if previous.outcome == GmailInterviewMail.OUTCOME_LABEL_FAILED:
            _label(client, previous, settings.interview_label)  # the steps are in; retry the label
            session.commit()
        summary.skipped += 1
        return

    try:
        record = _register(session, service, message)
    except OpenRouterNotConfigured:
        raise
    except OpenRouterError as exc:
        session.rollback()
        summary.failed += 1
        log.warning("OpenRouter failed for mail %s: %s", message.id, exc)
        return

    session.add(record)
    session.commit()
    if record.outcome == GmailInterviewMail.OUTCOME_APPLIED:
        _label(client, record, settings.interview_label)
        session.commit()
        summary.applied.append(
            {
                "message_id": record.message_id,
                "application_id": record.application_id,
                "company": record.company,
                "role": record.role,
                "steps": len(record.steps or []),
            }
        )
    summary.count(record.outcome)


def check_message(
    session: Session,
    client: AppsScriptClient,
    service: OpenRouterService,
    settings: GmailMonitorSettings,
    message: GmailMessage,
    summary: InterviewSummary,
) -> None:
    """``process_message`` that records an unexpected failure instead of raising it (one
    broken mail must not stop the run)."""
    try:
        process_message(session, client, service, settings, message, summary)
    except (OpenRouterNotConfigured, AppsScriptError):
        raise
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        log.exception("Interview-steps check of mail %s failed", message.id)
        if _processed(session, message.id) is None:
            session.add(_new_record(message, GmailInterviewMail.OUTCOME_ERROR, error=repr(exc)[:2000]))
            session.commit()
        summary.count(GmailInterviewMail.OUTCOME_ERROR)
