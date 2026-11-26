"""Filling in a work-history entry from the application it came from, as a background
(RQ) job.

Accepting an offer (``POST /api/applications/{id}/accept``) adds the position to the work
history seeded with what is already known (company, job title, technologies parsed from the
description) and marked ``PREFILL_QUEUED``, then queues ``prefill_work_entry(entry_id)``.
The task gives the chat model the job description, the application's steps and notes and
the company notes, and asks for the role, location, technologies and a short description of
the position. It only fills what the user has not changed in the meantime: ``location`` and
``context`` while still empty, ``role`` and ``tech`` while still the seeded values. The entry
ends ``PREFILL_DONE``, or ``PREFILL_FAILED`` when the model cannot be reached (the entry stays
as it was, ready to be edited by hand).
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from rq import Queue
from sqlalchemy.orm import Session

from app import llm_calls
from app.config import Settings, get_settings
from app.db import init_db, session_factory
from app.models import Application, WorkHistoryEntry
from app.services.applications import seeded_role, seeded_tech
from app.services.openrouter import OpenRouterError, OpenRouterService

log = logging.getLogger(__name__)

PREFILL_TIMEOUT = 300
"""RQ ``job_timeout`` (seconds): a single chat call."""
MAX_DESCRIPTION_CHARS = 20000
MAX_CONTEXT_CHARS = 2000
MAX_TECH = 30
NO_VALUE = frozenset({"null", "none", "n/a", "unknown", "not stated"})

SYSTEM = ( """
Act as an expert resume writer and career coach. Based on the role title and job description provided, 
write a compelling work experience section for my CV/resume. Answer with a single JSON object and nothing else. """
)
PROMPT = """
Write a compelling work experience section for my CV/resume as a JSON object
{{"role": ..., "location": ..., "tech": [...], "context": ...}} where
- "role" is the job title as the candidate would list it on a CV (keep the job's own title
  unless it is clearly not a title),
- "location" is where the job is based as stated (city and country, or "Remote" /
  "Hybrid, <city>"), or null when not stated,
- "tech" lists the technologies, languages, frameworks and tools the role works with, most
  important first, as short names ("Python", "PostgreSQL", "Kubernetes"),
- "context" is 2-4 sentences, in an implied first-person perspective. Translate the listed responsibilities into concrete accomplishments rather 
    than a passive list of duties. Focus on outcomes, efficiency, and value added. Naturally weave in the most important keywords, tools, and hard/soft 
    skills found in the job description.

Job title: {title}
Company: {company}
Job description:
{description}
"""


def _strip_fences(text: str) -> str:
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())


def _clean(value: object, limit: int) -> str | None:
    text = " ".join(value.split()) if isinstance(value, str) else ""
    if text.casefold() in NO_VALUE:
        return None
    return text[:limit] or None


def _clean_tech(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for item in value:
        name = _clean(item, 64)
        if name and name.casefold() not in {n.casefold() for n in names}:
            names.append(name)
    return names[:MAX_TECH]


def parse_reply(reply: str) -> dict[str, Any]:
    """``{"role", "location", "tech", "context"}`` read from the model's reply; missing or
    malformed values are ``None`` (``[]`` for ``tech``)."""
    try:
        data = json.loads(_strip_fences(reply))
    except ValueError:
        data = None
    if not isinstance(data, dict):
        data = {}
    context = data.get("context")
    return {
        "role": _clean(data.get("role"), 256),
        "location": _clean(data.get("location"), 256),
        "tech": _clean_tech(data.get("tech")),
        "context": (context.strip()[:MAX_CONTEXT_CHARS] or None) if isinstance(context, str) else None,
    }


def build_prompt(application: Application) -> str:
    parsed = application.job_parse_result
    company = parsed.company
    return PROMPT.format(
        title=parsed.title or "(unknown)",
        company=company.name if company is not None else "(unknown)",
        description=(parsed.description or "(no description)")[:MAX_DESCRIPTION_CHARS],
    )


def apply_prefill(entry: WorkHistoryEntry, data: dict[str, Any]) -> None:
    """Copy ``data`` (see ``parse_reply``) onto ``entry`` without overwriting what the user
    already changed."""
    parsed = entry.application.job_parse_result if entry.application is not None else None
    if parsed is None:
        return
    if data.get("role") and entry.role == seeded_role(parsed):
        entry.role = data["role"]
    if data.get("location") and not (entry.location or "").strip():
        entry.location = data["location"]
    if data.get("tech") and list(entry.tech or []) == seeded_tech(parsed):
        entry.tech = data["tech"]
    if data.get("context") and not (entry.context or "").strip():
        entry.context = data["context"]


def prefill(session: Session, entry: WorkHistoryEntry, service: OpenRouterService) -> WorkHistoryEntry | None:
    """Fill ``entry`` in from its application (see the module docstring) and commit;
    ``None`` when the entry was deleted meanwhile."""
    entry_id = entry.id
    application = entry.application
    if application is None:
        entry.prefill_state = WorkHistoryEntry.PREFILL_DONE
        session.commit()
        return entry
    try:
        reply = service.chat(
            build_prompt(application), system=SYSTEM, temperature=0, call=llm_calls.WORK_HISTORY_PREFILL
        ).text
    except OpenRouterError:
        log.exception("Could not prefill work-history entry %d", entry_id)
        state, data = WorkHistoryEntry.PREFILL_FAILED, None
    else:
        state, data = WorkHistoryEntry.PREFILL_DONE, parse_reply(reply)
    # Re-read the entry: the user may have edited (or deleted) it while the model answered.
    session.expire_all()
    entry = session.get(WorkHistoryEntry, entry_id)
    if entry is None:
        return None
    if data is not None:
        apply_prefill(entry, data)
    entry.prefill_state = state
    session.commit()
    return entry


def prefill_work_entry(entry_id: int) -> dict[str, Any]:
    """RQ entry point: :func:`prefill` the ``work_history`` row ``entry_id``."""
    init_db()
    with session_factory()() as session:
        entry = session.get(WorkHistoryEntry, entry_id)
        if entry is not None:
            entry = prefill(session, entry, OpenRouterService(session))
        if entry is None:
            log.info("Work-history entry %d is gone; nothing to prefill", entry_id)
            return {"entry_id": entry_id, "prefill_state": None}
        return {"entry_id": entry_id, "prefill_state": entry.prefill_state}


def enqueue_prefill(session: Session, queue: Queue, entry: WorkHistoryEntry, settings: Settings | None = None) -> None:
    """Queue :func:`prefill_work_entry` for ``entry``; when the queue is unreachable the entry
    is marked ``PREFILL_FAILED`` instead of raising. Commits."""
    settings = settings or get_settings()
    try:
        queue.enqueue(
            prefill_work_entry,
            entry.id,
            job_id=uuid.uuid4().hex,
            job_timeout=PREFILL_TIMEOUT,
            result_ttl=settings.job_result_ttl,
            failure_ttl=settings.job_result_ttl,
            meta={"work_history_id": entry.id, "application_id": entry.application_id},
            description=f"prefill work history {entry.id} from application {entry.application_id}",
        )
    except Exception:
        log.exception("Could not enqueue the prefill of work-history entry %d", entry.id)
        entry.prefill_state = WorkHistoryEntry.PREFILL_FAILED
        session.commit()
