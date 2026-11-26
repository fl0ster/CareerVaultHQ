"""Comparing the open offers side by side, for the hints on the Offers page cards.

``compare_offers`` sends every application currently in ``OFFER`` to the chat model in one
prompt (with the candidate profile, the job descriptions, where salary and benefits usually
are, and the user's notes) and asks, per offer, for a few short highlights: what it does
*best* of all the offers, what only it has (*unique*), a general *strength* when there is
nothing to compare against, and one trade-off to *watch out* for, plus the *top pick* among
them. The answer is stored in ``offer_comparisons`` under a fingerprint of everything the
prompt was built from, so it is generated again only when the offers change.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app import llm_calls
from app.models import Application, ApplicationEvent, CandidateProfile, JobParseResult, OfferComparison
from app.services.applications import OFFER_STATUS, held_rounds
from app.services.candidate_profile import latest_profile
from app.services.openrouter import OpenRouterError, OpenRouterService

PROMPT_VERSION = 1
"""Part of the fingerprint: bump it when the prompt changes so stored comparisons are redone."""
MAX_DESCRIPTION_CHARS = 6_000
"""Per offer; salary and benefits sections are kept by the scrapers near the top or bottom,
so the description is cut in the middle rather than at the end."""
MAX_HIGHLIGHTS = 3
MAX_HINT_CHARS = 60
MAX_REASON_CHARS = 120

HINT_KINDS: frozenset[str] = frozenset({"best", "unique", "strength"})

SYSTEM = (
    "You help a job seeker choose between the job offers they received. You get their profile "
    "and every open offer (job description, which often lists salary, contract and benefits, "
    "plus their own notes). For each offer give at most 3 highlights and at most one trade-off, "
    "so the offers can be compared at a glance.\n"
    "Highlight kinds:\n"
    '- "best": the offer is clearly better than every other offer on this point '
    "(e.g. the highest salary, the most remote days).\n"
    '- "unique": only this offer has it (e.g. a 4-day week, equity, a training budget).\n'
    '- "strength": good in general; use it only when there is a single offer or nothing '
    "comparable in the others.\n"
    "Put the most decision-relevant points first (pay, contract, remote work, growth, stack). "
    '"watch_out" is the one weakness most worth weighing before accepting, or null.\n'
    "Rules: use only facts stated in the input, never guess numbers; give concrete values when "
    'stated ("28-32k PLN B2B", "100% remote"); every text at most 6 words, no trailing period; '
    'never repeat the job title or company. "top_pick" is the id of the offer that fits the '
    "candidate best, or null when there is only one offer or too little to tell; "
    '"top_pick_reason" says why in at most 12 words.\n'
    "Answer with a single JSON object and nothing else:\n"
    '{"top_pick": <id or null>, "top_pick_reason": "<text>" or null, "offers": [{"id": <id>, '
    '"highlights": [{"kind": "best" | "unique" | "strength", "text": "<text>"}], '
    '"watch_out": "<text>" or null}]}'
)


def offer_applications(session: Session) -> list[Application]:
    """Applications whose current state is ``OFFER``, oldest first."""
    applications = (
        session.scalars(
            select(Application)
            .options(
                joinedload(Application.job_parse_result).joinedload(JobParseResult.company),
                selectinload(Application.events).joinedload(ApplicationEvent.status),
            )
            .order_by(Application.id)
        )
        .unique()
        .all()
    )
    return [a for a in applications if a.current_event is not None and a.current_event.status.key == OFFER_STATUS]


def _description(parsed: JobParseResult) -> str:
    text = (parsed.description or "").strip()
    if len(text) <= MAX_DESCRIPTION_CHARS:
        return text
    half = MAX_DESCRIPTION_CHARS // 2
    return f"{text[:half]}\n[...]\n{text[-half:]}"


def _event_notes(application: Application) -> list[str]:
    return [f"{e.status.label}: {e.note.strip()}" for e in application.history if e.note.strip()]


def _offer_facts(application: Application) -> dict[str, Any]:
    """Everything about one offer that goes into the prompt (and so into the fingerprint)."""
    parsed = application.job_parse_result
    company = parsed.company
    return {
        "id": application.id,
        "title": parsed.title or "unknown",
        "company": company.name if company is not None else "unknown",
        "start_date": application.start_date.isoformat() if application.start_date else None,
        "rounds": len(held_rounds(application)),
        "notes": application.notes.strip(),
        "company_notes": (company.notes or "").strip() if company is not None else "",
        "event_notes": _event_notes(application),
        "description": _description(parsed),
    }


def fingerprint(facts: list[dict[str, Any]], profile: CandidateProfile | None) -> str:
    payload = {
        "version": PROMPT_VERSION,
        "profile": [profile.id, profile.content] if profile is not None else None,
        "offers": facts,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def build_prompt(facts: list[dict[str, Any]], profile: CandidateProfile | None) -> str:
    parts = []
    if profile is not None and profile.content.strip():
        parts.append(f"Candidate profile:\n{profile.content.strip()}")
    for offer in facts:
        lines = [
            f"=== Offer id {offer['id']} ===",
            f"Job title: {offer['title']}",
            f"Company: {offer['company']}",
            f"Start date: {offer['start_date'] or 'not agreed yet'}",
            f"Interview rounds held: {offer['rounds']}",
        ]
        if offer["notes"]:
            lines.append(f"Candidate's notes on this offer:\n{offer['notes']}")
        if offer["company_notes"]:
            lines.append(f"Candidate's notes on the company:\n{offer['company_notes']}")
        if offer["event_notes"]:
            lines.append("Notes from the recruitment:\n" + "\n".join(f"- {n}" for n in offer["event_notes"]))
        lines.append(f"Job description:\n{offer['description'] or '(none)'}")
        parts.append("\n".join(lines))
    parts.append(f"Compare these {len(facts)} offer(s).")
    return "\n\n".join(parts)


def _strip_fences(text: str) -> str:
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())


def _text(value: object, limit: int) -> str | None:
    text = " ".join(value.split()).rstrip(".") if isinstance(value, str) else ""
    if text.casefold() in {"", "null", "none", "n/a"}:
        return None
    return text[:limit]


def _id(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and (match := re.search(r"\d+", value)):
        return int(match.group())
    return None


def parse_reply(reply: str, offer_ids: list[int]) -> dict[str, Any]:
    """The model's answer as the stored ``result``: one entry per offer in ``offer_ids``
    (empty when the model left it out), unknown ids and kinds dropped, texts trimmed.
    Raises ``OpenRouterError`` when the reply is not a JSON object."""
    try:
        data = json.loads(_strip_fences(reply))
    except ValueError as exc:
        raise OpenRouterError("the model did not answer with JSON") from exc
    if not isinstance(data, dict):
        raise OpenRouterError("the model did not answer with a JSON object")

    by_id: dict[int, dict[str, Any]] = {}
    for item in data.get("offers") or []:
        if not isinstance(item, dict) or (offer_id := _id(item.get("id"))) not in offer_ids or offer_id in by_id:
            continue
        highlights = []
        for hint in item.get("highlights") or []:
            if not isinstance(hint, dict) or hint.get("kind") not in HINT_KINDS:
                continue
            if (text := _text(hint.get("text"), MAX_HINT_CHARS)) is not None:
                highlights.append({"kind": hint["kind"], "text": text})
        by_id[offer_id] = {
            "application_id": offer_id,
            "highlights": highlights[:MAX_HIGHLIGHTS],
            "watch_out": _text(item.get("watch_out"), MAX_HINT_CHARS),
        }

    top_pick = _id(data.get("top_pick"))
    if top_pick not in offer_ids or len(offer_ids) < 2:
        top_pick = None
    return {
        "top_pick_id": top_pick,
        "top_pick_reason": _text(data.get("top_pick_reason"), MAX_REASON_CHARS) if top_pick is not None else None,
        "offers": [by_id.get(i, {"application_id": i, "highlights": [], "watch_out": None}) for i in offer_ids],
    }


def _empty() -> dict[str, Any]:
    return {"top_pick_id": None, "top_pick_reason": None, "offers": [], "generated_at": None}


def compare_offers(session: Session, service: OpenRouterService, *, refresh: bool = False) -> dict[str, Any]:
    """The comparison of the current offers: the stored one when nothing it was made from
    changed (unless ``refresh``), otherwise a new one, stored in place of the old ones.
    No offers means no call. Raises ``OpenRouterError`` when the chat call fails."""
    applications = offer_applications(session)
    if not applications:
        return _empty()
    profile = latest_profile(session)
    facts = [_offer_facts(a) for a in applications]
    key = fingerprint(facts, profile)

    stored = session.scalar(select(OfferComparison).where(OfferComparison.fingerprint == key))
    if stored is not None and not refresh:
        return {**stored.result, "generated_at": _utc(stored.created_at)}

    reply = service.chat(
        build_prompt(facts, profile),
        system=SYSTEM,
        temperature=0.2,
        max_tokens=800,
        call=llm_calls.OFFER_COMPARISON,
    )
    result = parse_reply(reply.text, [a.id for a in applications])
    session.execute(delete(OfferComparison))
    row = OfferComparison(fingerprint=key, result=result, openrouter_call_id=reply.call_id)
    session.add(row)
    session.commit()
    return {**result, "generated_at": _utc(row.created_at)}


def _utc(value: datetime) -> datetime:
    """SQLite drops the offset; stored timestamps are UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value
