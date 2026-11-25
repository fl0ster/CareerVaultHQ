"""Lazy candidate-profile generation.

The candidate profile is derived from the work history via OpenRouter. It is not generated
up front: :func:`current_profile` is called wherever the profile is needed and regenerates
it only when it is missing or the work history changed since the latest profile was built
(tracked by ``CandidateProfile.work_history_id``, a hash of the exported work history).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import llm_calls
from app.models import CandidateProfile, WorkHistoryEntry
from app.services.openrouter import OpenRouterError, OpenRouterService

log = logging.getLogger(__name__)

"""``openrouter_calls.source`` label for profile generation."""

PROFILE_SYSTEM_PROMPT = (
    "You are an expert technical recruiter. You write candidate profiles based on the "
    "provided job history that reflects the strengths, skills and experience of the individual."
)

PROFILE_PROMPT = """\
Below is the candidate's full work history as JSON (newest position first; a null date_end
means a current position).

Write a comprehensive candidate profile in plain prose (no markdown headings).
Cover:

- total years of experience and the overall career trajectory;
- seniority level and the kinds of roles held (engineer, lead, architect, ...);
- the technology stack, grouped by how deep and how recent the experience is;
- domains and industries worked in, and the type of companies (startup, enterprise, ...);
- locations and any indication of remote or on-site work;
- notable responsibilities, achievements and areas of strength;
- sensible directions for a career growth, or next steps given the experience from the work history

Do not invent facts that are not supported by the work history.

Work history:
{work_history}
"""


def latest_profile(session: Session) -> CandidateProfile | None:
    return session.scalar(select(CandidateProfile).order_by(CandidateProfile.id.desc()).limit(1))


def _month(value: date | None) -> str | None:
    return value.strftime("%b %Y") if value else None


def _work_history_payload(session: Session) -> list[dict]:
    """The work history in the shape of ``GET /api/work-history/json``, newest first. Pending
    positions (starting in the future) are left out until they start, and so are education
    and certificates (the profile describes the work experience)."""
    entries = session.scalars(
        select(WorkHistoryEntry)
        .where(WorkHistoryEntry.kind == WorkHistoryEntry.KIND_JOB, WorkHistoryEntry.date_start <= date.today())
        .order_by(WorkHistoryEntry.date_start.desc(), WorkHistoryEntry.id.desc())
    ).all()
    return [
        {
            "date_start": _month(e.date_start),
            "date_end": _month(e.date_end),
            "employer": e.employer,
            "role": e.role,
            "location": e.location,
            "tech": ", ".join(e.tech),
            "context": e.context,
        }
        for e in entries
    ]


def work_history_id(work_history: list[dict]) -> str | None:
    """Stable hash of the exported work history; ``None`` when it is empty."""
    if not work_history:
        return None
    blob = json.dumps(work_history, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


def current_profile(session: Session, ai_service: OpenRouterService) -> tuple[CandidateProfile | None, bool]:
    """The profile to use right now, generating a new one first when needed.

    Returns ``(profile, created)``. A new profile is generated (and committed) when the work
    history is non-empty and the latest profile is missing or was built from a different
    work history. With no work history the latest profile (if any) is returned as is.
    Raises :class:`OpenRouterError` when generation fails.
    """
    latest = latest_profile(session)
    work_history = _work_history_payload(session)
    wh_id = work_history_id(work_history)
    if wh_id is None or (latest is not None and latest.work_history_id == wh_id):
        return latest, False

    log.info("Work history changed or no profile yet; generating a new candidate profile")
    prompt = PROFILE_PROMPT.format(work_history=json.dumps(work_history, indent=2))
    result = ai_service.chat(prompt, system=PROFILE_SYSTEM_PROMPT, call=llm_calls.CANDIDATE_PROFILE)
    content = result.text.strip()
    if not content:
        raise OpenRouterError("empty response from OpenRouter")

    profile = CandidateProfile(content=content, work_history_id=wh_id)
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile, True


def current_profile_ids(session: Session) -> set[int]:
    """Ids of the profiles built from the *current* work history. A job scored against any
    other profile is *outdated*: the work history changed since, so it can be re-scored.

    Profiles are generated lazily (see :func:`current_profile`), so right after the work
    history is edited no profile matches it yet and every score is outdated. With an empty
    work history the latest profile (if any) counts as current."""
    wh_id = work_history_id(_work_history_payload(session))
    if wh_id is None:
        latest = latest_profile(session)
        return {latest.id} if latest is not None else set()
    return set(session.scalars(select(CandidateProfile.id).where(CandidateProfile.work_history_id == wh_id)))
