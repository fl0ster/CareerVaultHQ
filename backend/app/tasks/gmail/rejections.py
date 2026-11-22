"""Gmail rejection monitor as a background (RQ) job.

``check_rejection_mails()`` fetches the unread inbox mails of the monitored account through
the Apps Script web app (see ``app.integrations.gmail``) and, for each mail not looked at
before:

1. asks the Jev decisions API whether it is a final rejection of a job application
   (``is_rejection``); below ``gmail_monitor_settings.threshold`` the mail is left alone;
2. asks a chat model for the hiring company and the role (strict JSON);
3. matches them against the *open* applications (``APPLIED`` recorded, no final state):
   the company must match by name or alias; when several open applications are at that
   company, the role must single one out. No match, or an ambiguous one, leaves the mail
   alone;
4. records ``REJECTED`` on the application (``source="gmail"``, shown with a lightning bolt
   in the UI), then marks the mail read and labels it.

Only high-confidence, unambiguous cases are acted on; everything else stays unread in the
inbox for the user. Every mail is recorded in ``gmail_processed_mails`` with its outcome so
it is never sent to OpenRouter twice (a failing OpenRouter call is not recorded, so the mail
is retried by the next run).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.db import init_db, session_factory
from app.integrations.gmail import AppsScriptClient, AppsScriptError, GmailMessage
from app.models import (
    Application,
    ApplicationEvent,
    Company,
    GmailMonitorSettings,
    GmailProcessedMail,
    JobParseResult,
)
from app.scheduler.common import aware
from app.services.applications import (
    REJECTED_STATUS,
    EventRejected,
    is_open,
    record_event,
)
from app.services.companies import find_company, normalize_company_name
from app.services.gmail_monitor import (
    MAX_MESSAGES_PER_RUN,
    client_for,
    get_monitor_settings,
    is_configured,
)
from app.services.openrouter import (
    OpenRouterError,
    OpenRouterNotConfigured,
    OpenRouterService,
)

log = logging.getLogger(__name__)

SOURCE = "tasks.gmail_rejections"
"""``openrouter_calls.source`` label for calls made by this task."""

COMPANY_THRESHOLD = 0.85
"""Minimum company-name similarity (0-1) for an application to be a candidate."""
ROLE_THRESHOLD = 0.8
"""Minimum role/title similarity for the best application when several are candidates."""
ROLE_MARGIN = 0.15
"""How much the best role similarity must beat the runner-up by."""
PREFIX_MIN_LENGTH = 4
"""A company name that is a whole-word prefix of the other ("Acme" / "Acme Software") only
counts when it has at least this many characters."""
PREFIX_SCORE = 0.9

QUESTION_NAME = "is_rejection"
QUESTIONS: dict[str, dict[str, Any]] = {
    QUESTION_NAME: {
        "type": "noul",
        "instructions": (
            "Is this e-mail a final rejection of the recipient's job application, i.e. the "
            "employer or recruiter tells the candidate they will not move forward with them "
            "for a specific position?"
        ),
        "criteria": {
            "true": (
                "The mail clearly states a decision not to proceed with the candidate's "
                "application (e.g. 'we decided to move forward with other candidates', "
                "'unfortunately we will not be continuing with your application')."
            ),
            "false": (
                "Anything else: application received confirmations, interview invitations "
                "or scheduling, requests for information, assessments, job offers, job "
                "alerts, newsletters, marketing, 'position on hold' notices without a "
                "decision about the candidate, or mails not about a job application at all."
            ),
        },
    }
}

EXTRACTION_SYSTEM = (
    "You extract data from job application e-mails. Answer with a single JSON object and "
    "nothing else."
)
EXTRACTION_PROMPT = """The e-mail below is a rejection of a job application.
Return a JSON object {{"company": ..., "role": ...}} where
- "company" is the name of the hiring company the candidate applied to (not the recruitment
  agency or applicant tracking system that sent the mail, unless it is the employer itself),
- "role" is the job title of the position the candidate applied for.
Use null for a value the mail does not state. Do not guess.

From: {sender}
Subject: {subject}

{body}"""

LEGAL_FORM_TOKENS = frozenset(
    {
        "sp", "z", "o", "s", "a", "sa", "sk", "spolka", "akcyjna", "komandytowa", "gmbh",
        "inc", "ltd", "llc", "ag", "bv", "nv", "plc", "corp", "corporation", "co", "limited",
        "oy", "ab", "as", "srl", "sas", "sarl", "kft", "se", "spa",
    }
)  # fmt: skip
"""Trailing tokens dropped before comparing company names ("Acme Sp. z o.o." ~ "Acme")."""


# --------------------------------------------------------------------------- matching


def core_company_name(raw: str) -> str:
    """Normalised company name without its trailing legal form."""
    tokens = normalize_company_name(raw).split()
    while len(tokens) > 1 and tokens[-1] in LEGAL_FORM_TOKENS:
        tokens.pop()
    return " ".join(tokens)


def company_similarity(a: str, b: str) -> float:
    """Similarity (0-1) of two company names, ignoring legal forms."""
    a, b = core_company_name(a), core_company_name(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    short, long = sorted((a, b), key=len)
    if len(short) >= PREFIX_MIN_LENGTH and long.startswith(short + " "):
        return PREFIX_SCORE
    return SequenceMatcher(None, a, b).ratio()


def role_similarity(a: str, b: str) -> float:
    """Similarity (0-1) of two job titles, ignoring case, punctuation and word order
    ("Backend Developer, Senior" ~ "Senior Backend Developer")."""

    def words(text: str) -> str:
        return " ".join(sorted(re.findall(r"\w+", text.casefold())))

    a, b = words(a), words(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _company_names(company: Company | None) -> list[str]:
    if company is None:
        return []
    return [company.name, *(alias.alias for alias in company.aliases)]


def open_applications(session: Session) -> list[Application]:
    rows = session.scalars(
        select(Application)
        .options(
            joinedload(Application.job_parse_result)
            .joinedload(JobParseResult.company)
            .selectinload(Company.aliases),
            selectinload(Application.events).joinedload(ApplicationEvent.status),
        )
        .execution_options(populate_existing=True)
    ).unique()
    return [a for a in rows if is_open(a)]


@dataclass
class Match:
    application: Application | None
    outcome: str
    detail: str = ""


def match_application(
    session: Session, applications: list[Application], company: str, role: str | None
) -> Match:
    """The single open application the rejection refers to, or why there is none."""
    known = find_company(session, company)
    candidates = []
    for application in applications:
        parsed = application.job_parse_result
        if known is not None and parsed.company_id == known.id:
            candidates.append(application)
            continue
        names = _company_names(parsed.company)
        if names and max(company_similarity(company, n) for n in names) >= COMPANY_THRESHOLD:
            candidates.append(application)
    if not candidates:
        return Match(None, GmailProcessedMail.OUTCOME_NO_MATCH, "no open application at company")
    if len(candidates) == 1:
        return Match(candidates[0], GmailProcessedMail.OUTCOME_APPLIED)
    if not role:
        return Match(
            None,
            GmailProcessedMail.OUTCOME_AMBIGUOUS,
            f"{len(candidates)} open applications at the company and no role in the mail",
        )
    scored = sorted(
        ((role_similarity(role, a.job_parse_result.title or ""), a) for a in candidates),
        key=lambda pair: pair[0],
        reverse=True,
    )
    (best_score, best), (runner_up, _) = scored[0], scored[1]
    if best_score >= ROLE_THRESHOLD and best_score - runner_up >= ROLE_MARGIN:
        return Match(best, GmailProcessedMail.OUTCOME_APPLIED)
    return Match(
        None,
        GmailProcessedMail.OUTCOME_AMBIGUOUS,
        f"{len(candidates)} open applications at the company; the role does not single one out",
    )


# --------------------------------------------------------------------------- OpenRouter


def _strip_fences(text: str) -> str:
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())


def _mail_state(message: GmailMessage) -> dict[str, Any]:
    return {
        "from": message.sender,
        "subject": message.subject,
        "received_at": message.received_at.isoformat() if message.received_at else None,
        "body": message.body,
    }


def rejection_probability(service: OpenRouterService, message: GmailMessage) -> float:
    decision = service.decide(
        state=_mail_state(message), questions=QUESTIONS, source=SOURCE, private=True
    )
    return decision.noul(QUESTION_NAME)


def extract_company_and_role(
    service: OpenRouterService, message: GmailMessage
) -> tuple[str | None, str | None]:
    """``(company, role)`` named in the mail; ``None`` for what could not be read."""
    reply = service.chat(
        EXTRACTION_PROMPT.format(sender=message.sender, subject=message.subject, body=message.body),
        system=EXTRACTION_SYSTEM,
        temperature=0,
        source=SOURCE,
        private=True,
    ).text
    try:
        data = json.loads(_strip_fences(reply))
    except ValueError:
        return None, None
    if not isinstance(data, dict):
        return None, None

    def clean(value: object) -> str | None:
        text = " ".join(value.split()) if isinstance(value, str) else ""
        return text[:512] or None

    return clean(data.get("company")), clean(data.get("role"))


# --------------------------------------------------------------------------- run


@dataclass
class RunSummary:
    fetched: int = 0
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
            "fetched": self.fetched,
            "skipped": self.skipped,
            "failed": self.failed,
            "outcomes": dict(self.outcomes),
            "applied": list(self.applied),
        }


def _processed(session: Session, message_id: str) -> GmailProcessedMail | None:
    return session.scalar(
        select(GmailProcessedMail).where(GmailProcessedMail.message_id == message_id)
    )


def _new_record(message: GmailMessage, outcome: str, **fields: Any) -> GmailProcessedMail:
    return GmailProcessedMail(
        message_id=message.id,
        thread_id=message.thread_id,
        subject=message.subject[:1024],
        sender=message.sender[:512],
        received_at=message.received_at,
        outcome=outcome,
        **fields,
    )


def _mark(client: AppsScriptClient, record: GmailProcessedMail, label: str) -> None:
    """Mark the mail read and labelled; ``record.outcome`` reflects whether it worked."""
    try:
        client.mark(record.message_id, label)
    except AppsScriptError as exc:
        log.warning("Marking mail %s failed: %s", record.message_id, exc)
        record.outcome = GmailProcessedMail.OUTCOME_MARK_FAILED
        record.error = str(exc)[:2000]
    else:
        record.outcome = GmailProcessedMail.OUTCOME_APPLIED
        record.error = None


def process_message(
    session: Session,
    client: AppsScriptClient,
    service: OpenRouterService,
    settings: GmailMonitorSettings,
    message: GmailMessage,
    summary: RunSummary,
) -> None:
    """Handle one mail and record its outcome (committed)."""
    previous = _processed(session, message.id)
    if previous is not None:
        if previous.outcome == GmailProcessedMail.OUTCOME_MARK_FAILED:
            _mark(client, previous, settings.label)  # the rejection is in; retry the label
            session.commit()
        summary.skipped += 1
        return

    try:
        probability = rejection_probability(service, message)
        if probability < settings.threshold:
            record = _new_record(
                message, GmailProcessedMail.OUTCOME_NOT_REJECTION, probability=probability
            )
        else:
            company, role = extract_company_and_role(service, message)
            record = _register(session, message, probability, company, role)
    except OpenRouterNotConfigured:
        raise
    except OpenRouterError as exc:
        session.rollback()
        summary.failed += 1
        log.warning("OpenRouter failed for mail %s: %s", message.id, exc)
        return

    session.add(record)
    session.commit()
    if record.outcome == GmailProcessedMail.OUTCOME_APPLIED:
        _mark(client, record, settings.label)
        session.commit()
        summary.applied.append(
            {
                "message_id": record.message_id,
                "application_id": record.application_id,
                "company": record.company,
                "role": record.role,
                "probability": record.probability,
            }
        )
    summary.count(record.outcome)


def _rejection_time(application: Application, message: GmailMessage) -> datetime:
    """When the mail arrived, but never before the application's latest state: the
    rejection has to become the current state."""
    when = message.received_at or datetime.now(UTC)
    current = application.current_event
    latest = aware(current.occurred_at) if current is not None else None
    return max(when, latest) if latest is not None else when


def _register(
    session: Session,
    message: GmailMessage,
    probability: float,
    company: str | None,
    role: str | None,
) -> GmailProcessedMail:
    """Record ``REJECTED`` on the matching application (not committed); the returned record
    says what happened."""
    fields: dict[str, Any] = {"probability": probability, "company": company, "role": role}
    if not company:
        return _new_record(message, GmailProcessedMail.OUTCOME_EXTRACTION_FAILED, **fields)
    match = match_application(session, open_applications(session), company, role)
    if match.application is None:
        return _new_record(message, match.outcome, error=match.detail or None, **fields)
    try:
        record_event(
            session,
            match.application,
            REJECTED_STATUS,
            note=f"Rejection mail detected in Gmail: {message.subject}".strip()[:2000],
            occurred_at=_rejection_time(match.application, message),
            source=ApplicationEvent.SOURCE_GMAIL,
            source_ref=message.id,
        )
    except EventRejected as exc:
        return _new_record(message, GmailProcessedMail.OUTCOME_NO_MATCH, error=str(exc), **fields)
    return _new_record(
        message,
        GmailProcessedMail.OUTCOME_APPLIED,
        application_id=match.application.id,
        **fields,
    )


def run_check(
    session: Session,
    client: AppsScriptClient,
    service: OpenRouterService,
    settings: GmailMonitorSettings,
) -> RunSummary:
    """Fetch the candidate mails and process them one by one."""
    summary = RunSummary()
    messages = client.list_messages(settings.lookback_days, settings.label, MAX_MESSAGES_PER_RUN)
    summary.fetched = len(messages)
    for message in messages:
        try:
            process_message(session, client, service, settings, message, summary)
        except (OpenRouterNotConfigured, AppsScriptError):
            raise
        except Exception as exc:  # noqa: BLE001 - one broken mail must not stop the run
            session.rollback()
            log.exception("Processing mail %s failed", message.id)
            if _processed(session, message.id) is None:
                session.add(
                    _new_record(message, GmailProcessedMail.OUTCOME_ERROR, error=repr(exc)[:2000])
                )
                session.commit()
            summary.count(GmailProcessedMail.OUTCOME_ERROR)
    return summary


class NotConfigured(RuntimeError):
    """The monitored address or the web app URL is missing."""


def check_rejection_mails() -> dict[str, Any]:
    """RQ entry point; returns the run summary (see ``RunSummary.as_dict``). The outcome is
    also stored on the settings row (``last_run_at``, ``last_status``, ``last_error``)."""
    init_db()
    with session_factory()() as session:
        settings = get_monitor_settings(session)
        started = datetime.now(UTC)
        try:
            if not is_configured(settings):
                raise NotConfigured("set the monitored e-mail and the Apps Script web app URL")
            summary = run_check(session, client_for(settings), OpenRouterService(session), settings)
        except Exception as exc:
            session.rollback()
            settings.last_run_at = started
            settings.last_status = "failed"
            settings.last_error = f"{type(exc).__name__}: {exc}"[:2000]
            session.commit()
            raise
        settings.last_run_at = started
        settings.last_status = "ok"
        settings.last_error = None
        settings.last_summary = summary.as_dict()
        session.commit()
        log.info("Gmail rejection check: %s", settings.last_summary)
        return summary.as_dict()
