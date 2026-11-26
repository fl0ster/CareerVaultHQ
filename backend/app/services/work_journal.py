"""The work journal of a position: raw notes in, truthful polished career material out.

The user logs what they did at a position (``WorkJournalEntry``), as often as they like. The
notes are never rewritten. From them the LLM builds, lazily (the first time they are
requested after the notes changed, never on a schedule; in the RQ worker, see
``app.tasks.work_history.journal``, or inside CV generation, never in an API request):

* one ``WorkJournalMonth`` per month with notes: a short summary, the accomplishments and
  the technologies used that month. A month is *stale* when its notes no longer hash to the
  ``source_hash`` it was built from;
* the position's ``journal_context`` (a CV-style description built from the monthly
  summaries) and ``journal_tech`` (the summaries' technologies, most frequent first). They are
  stale when the summaries no longer hash to ``journal_hash``. A description that fails the
  truthfulness check is not retried until the summaries change: ``journal_failed_hash``
  remembers the summaries it failed for.

``WorkHistoryEntry.effective_context`` / ``effective_tech`` use them only while the user's
own ``context`` / ``tech`` are blank: a user edit is never overwritten, and clearing it brings
the journal's version back.

Truthfulness: the prompts allow only facts from the notes; technologies not literally named
in the notes are dropped; every generated text is checked by the decisions model
(``JOURNAL_FAITHFUL``), retried once at temperature 0 when judged unfaithful and discarded
(keeping the previous version) when it still is.

A current position is *overdue* when its latest note is dated (``logged_on``, not when it was
saved) ``OVERDUE_AFTER`` or more ago (with no notes yet: when it was added to the app that long
ago), so backfilled notes for past days do not hide a missing update for this week.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import llm_calls
from app.models import WorkHistoryEntry, WorkJournalEntry, WorkJournalMonth
from app.services.openrouter import OpenRouterError, OpenRouterNotConfigured, OpenRouterService

log = logging.getLogger(__name__)

OVERDUE_AFTER = timedelta(days=7)
"""A current position without a journal note for this long is flagged on the Employment tab."""
FAITHFUL_THRESHOLD = 0.5
"""Minimum probability (``JOURNAL_FAITHFUL``) that a monthly summary is supported by its notes."""
CONTEXT_FAITHFUL_THRESHOLD = 0.3
"""The same for the role description, checked against the monthly summaries. Lower: condensing
several months into a few sentences is often judged too strictly."""
MAX_SUMMARY_CHARS = 2000
MAX_CONTEXT_CHARS = 2000
MAX_ACCOMPLISHMENTS = 8
MAX_ACCOMPLISHMENT_CHARS = 300
MAX_TECH = 30
MAX_NOTE_CHARS = 10_000
"""A single note is cut to this length (bodies are validated by the API, this is a backstop)."""

MONTH_SYSTEM = (
    "You turn a professional's raw work-journal notes into an accurate, polished monthly career log. "
    "You never invent anything: every statement must be directly supported by the notes. "
    "Answer with a single JSON object and nothing else."
)
MONTH_PROMPT = """Below are my raw work-journal notes for {month} at my position "{role}" at {employer}.
Write my career log for that month as a JSON object
{{"summary": ..., "accomplishments": [...], "tech": [...]}} where
- "summary" is 1-3 polished sentences in implied first person (no "I"), describing the work of
  the month as it would read in a career log,
- "accomplishments" lists the concrete things delivered, fixed, improved or achieved, one short
  CV-style line each (at most {max_accomplishments}); an empty list when the notes name none,
- "tech" lists the technologies, languages, frameworks, tools and platforms the notes name,
  spelled exactly as in the notes.
Rules - truthfulness comes first:
- Use only facts stated in the notes. Never add numbers, outcomes, impact, scale, people,
  technologies or responsibilities the notes do not state.
- You may rephrase and group, but not exaggerate (no "led" when the notes say "helped").
- Leave out complaints, negative remarks and private matters.
- When the notes are thin, write less rather than pad.

Notes (date: note):
{notes}
"""

CONTEXT_SYSTEM = (
    "You are an expert CV writer. You describe a position strictly from the career log you are given, "
    "never inventing anything. Reply with plain text only: no headings, bullets or markdown."
)
CONTEXT_PROMPT = """Below is the monthly career log of my position "{role}" at {employer} ({period}).
Write the description of this position for my CV and work history: 2-4 concise,
achievement-oriented sentences in implied first person (no "I"), leading with the most
significant work and results, naturally naming the key technologies.
Use only facts stated in the log; never add numbers, outcomes, technologies or
responsibilities it does not state.

Career log:
{log}
"""

FAITHFUL_QUESTION = "is_faithful"
FAITHFUL_QUESTIONS: dict[str, dict[str, Any]] = {
    FAITHFUL_QUESTION: {
        "type": "noul",
        "instructions": "Is every statement in the generated text supported by the source notes?",
        "criteria": {
            "true": (
                "Each claim (task, result, number, technology, responsibility, scope) is stated in or "
                "directly follows from the source; rephrasing and grouping are fine."
            ),
            "false": (
                "Something is invented or exaggerated: a result, number, impact, technology or "
                "responsibility the source does not state, or a stronger claim than the source makes."
            ),
        },
    }
}


# --- Hashes and staleness -------------------------------------------------------------------


def month_of(day: date) -> date:
    return day.replace(day=1)


def month_label(month: date) -> str:
    return month.strftime("%B %Y")


def _sha(data: object) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def notes_hash(notes: Iterable[WorkJournalEntry]) -> str:
    """Content hash of a month's notes: editing a note and changing it back keeps the summary."""
    return _sha(sorted((n.logged_on.isoformat(), n.body) for n in notes))


def months_hash(months: Iterable[WorkJournalMonth]) -> str | None:
    """Hash of the monthly summaries a role description is built from; ``None`` without any."""
    data = sorted((m.month.isoformat(), m.summary, list(m.accomplishments or []), list(m.tech or [])) for m in months)
    return _sha(data) if data else None


def notes_by_month(notes: Iterable[WorkJournalEntry]) -> dict[date, list[WorkJournalEntry]]:
    by_month: dict[date, list[WorkJournalEntry]] = {}
    for note in notes:
        by_month.setdefault(month_of(note.logged_on), []).append(note)
    return by_month


def stale_months(role: WorkHistoryEntry) -> list[date]:
    """Months whose summary is missing or was built from other notes, oldest first."""
    built = {m.month: m.source_hash for m in role.journal_months}
    return sorted(m for m, notes in notes_by_month(role.journal_entries).items() if built.get(m) != notes_hash(notes))


def is_stale(role: WorkHistoryEntry) -> bool:
    """Something in the role's journal needs (re)generating: a month summary, a summary of a
    month that no longer has notes, or the role description."""
    months_with_notes = {month_of(n.logged_on) for n in role.journal_entries}
    if stale_months(role) or any(m.month not in months_with_notes for m in role.journal_months):
        return True
    current = months_hash(role.journal_months)
    return current != role.journal_hash and current != role.journal_failed_hash


# --- Reply parsing and truthfulness guards --------------------------------------------------


def _strip_fences(text: str) -> str:
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())


def _clean(value: object, limit: int) -> str:
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def mentioned(name: str, text: str) -> bool:
    """``name`` appears in ``text`` as a whole word (case-insensitive): "Go" is not in "going"."""
    pattern = r"(?<![\w])" + re.escape(name.casefold()) + r"(?![\w])"
    return re.search(pattern, text.casefold()) is not None


def _clean_tech(value: object, source: str) -> list[str]:
    """Unique technology names, keeping only those literally named in ``source``."""
    names: list[str] = []
    for item in value if isinstance(value, list) else []:
        name = _clean(item, 64)
        if name and name.casefold() not in {n.casefold() for n in names} and mentioned(name, source):
            names.append(name)
    return names[:MAX_TECH]


def parse_month_reply(reply: str, notes_text: str) -> dict[str, Any]:
    """``{"summary", "accomplishments", "tech"}`` read from the model's reply; malformed values
    are empty and technologies not named in the notes are dropped."""
    try:
        data = json.loads(_strip_fences(reply))
    except ValueError:
        data = None
    if not isinstance(data, dict):
        data = {}
    raw_items = data.get("accomplishments")
    accomplishments = (
        [_clean(item, MAX_ACCOMPLISHMENT_CHARS) for item in raw_items if isinstance(item, str)]
        if (isinstance(raw_items, list))
        else []
    )
    return {
        "summary": _clean(data.get("summary"), MAX_SUMMARY_CHARS),
        "accomplishments": [a for a in accomplishments if a][:MAX_ACCOMPLISHMENTS],
        "tech": _clean_tech(data.get("tech"), notes_text),
    }


def is_faithful(
    service: OpenRouterService, source: object, generated: object, threshold: float = FAITHFUL_THRESHOLD
) -> bool:
    probability = service.decide(
        state={"source": source, "generated": generated},
        questions=FAITHFUL_QUESTIONS,
        call=llm_calls.JOURNAL_FAITHFUL,
    ).noul(FAITHFUL_QUESTION)
    if probability < threshold:
        log.info("Discarded a journal text judged unfaithful (%.2f): %r", probability, generated)
        return False
    return True


# --- Generation -----------------------------------------------------------------------------


def format_notes(notes: Sequence[WorkJournalEntry]) -> str:
    ordered = sorted(notes, key=lambda n: (n.logged_on, n.id or 0))
    return "\n".join(f"- {n.logged_on.isoformat()}: {' '.join(n.body.split())[:MAX_NOTE_CHARS]}" for n in ordered)


def summarise_month(
    service: OpenRouterService, role: WorkHistoryEntry, month: date, notes: Sequence[WorkJournalEntry]
) -> dict[str, Any] | None:
    """The polished log of one month (see ``parse_month_reply``), or ``None`` when no faithful
    one could be produced in two attempts. Raises ``OpenRouterError`` when the model fails."""
    notes_text = format_notes(notes)
    prompt = MONTH_PROMPT.format(
        month=month_label(month),
        role=role.role,
        employer=role.employer or "(employer not given)",
        max_accomplishments=MAX_ACCOMPLISHMENTS,
        notes=notes_text,
    )
    for temperature in (0.3, 0.0):
        reply = service.chat(prompt, system=MONTH_SYSTEM, temperature=temperature, call=llm_calls.JOURNAL_MONTH_SUMMARY)
        data = parse_month_reply(reply.text, notes_text)
        if data["summary"] and is_faithful(service, notes_text, data):
            return data
    return None


def aggregate_tech(months: Iterable[WorkJournalMonth]) -> list[str]:
    """The technologies of the monthly summaries: in most months first, then most recent; the
    most recent spelling wins."""
    counts: Counter[str] = Counter()
    spelling: dict[str, str] = {}
    latest: dict[str, date] = {}
    for month in sorted(months, key=lambda m: m.month, reverse=True):
        for name in month.tech or []:
            key = name.casefold()
            counts[key] += 1
            spelling.setdefault(key, name)
            latest.setdefault(key, month.month)
    order = sorted(counts, key=lambda k: (-counts[k], -latest[k].toordinal()))
    return [spelling[k] for k in order][:MAX_TECH]


def _career_log(months: Iterable[WorkJournalMonth]) -> list[dict[str, Any]]:
    return [
        {
            "month": month_label(m.month),
            "summary": m.summary,
            "accomplishments": list(m.accomplishments or []),
            "tech": list(m.tech or []),
        }
        for m in sorted(months, key=lambda m: m.month)
    ]


def build_role_context(service: OpenRouterService, role: WorkHistoryEntry, months: Sequence[WorkJournalMonth]) -> str | None:
    """The position's description from its monthly summaries, or ``None`` when no faithful one
    could be produced. Raises ``OpenRouterError`` when the model fails."""
    log_data = _career_log(months)
    period = f"{role.date_start:%b %Y} – {f'{role.date_end:%b %Y}' if role.date_end else 'present'}"
    prompt = CONTEXT_PROMPT.format(
        role=role.role,
        employer=role.employer or "(employer not given)",
        period=period,
        log=json.dumps(log_data, indent=2, ensure_ascii=False),
    )
    for temperature in (0.3, 0.0):
        reply = service.chat(prompt, system=CONTEXT_SYSTEM, temperature=temperature, call=llm_calls.JOURNAL_ROLE_CONTEXT)
        text = " ".join(reply.text.split())[:MAX_CONTEXT_CHARS]
        if text and is_faithful(service, log_data, text, CONTEXT_FAITHFUL_THRESHOLD):
            return text
    return None


def refresh_journal(session: Session, role: WorkHistoryEntry, service: OpenRouterService) -> list[str]:
    """Regenerate what is stale in ``role``'s journal (see the module docstring) and commit.
    Returns warnings for what could not be regenerated; the previous version is kept then.
    Raises ``OpenRouterNotConfigured`` when there is no API key (nothing can be generated)."""
    warnings: list[str] = []
    by_month = notes_by_month(role.journal_entries)
    built = {m.month: m for m in role.journal_months}
    for month, row in built.items():
        if month not in by_month:
            role.journal_months.remove(row)
    for month in sorted(by_month):
        notes = by_month[month]
        source_hash = notes_hash(notes)
        row = built.get(month)
        if row is not None and row.source_hash == source_hash:
            continue
        try:
            data = summarise_month(service, role, month, notes)
        except OpenRouterNotConfigured:
            raise
        except OpenRouterError as exc:
            log.warning("Could not summarise %s of work-history entry %d: %s", month, role.id, exc)
            warnings.append(f"{month_label(month)} could not be summarised right now ({exc}).")
            continue
        if data is None:
            warnings.append(
                f"No summary of {month_label(month)} passed the truthfulness check; "
                + ("the previous one is kept." if row is not None else "it will be retried next time.")
            )
            continue
        if row is None:
            row = WorkJournalMonth(month=month, source_hash=source_hash)
            role.journal_months.append(row)
        row.summary, row.accomplishments, row.tech = data["summary"], data["accomplishments"], data["tech"]
        row.source_hash = source_hash
        row.generated_at = datetime.now(UTC)

    months = list(role.journal_months)
    target_hash = months_hash(months)
    if target_hash != role.journal_hash:
        if target_hash is None:
            role.journal_context = role.journal_tech = role.journal_hash = role.journal_failed_hash = None
        else:
            role.journal_tech = aggregate_tech(months)
        # These very summaries already gave a description that failed the truthfulness check:
        # not retried until they change.
        if target_hash is not None and target_hash != role.journal_failed_hash:
            try:
                context = build_role_context(service, role, months)
            except OpenRouterNotConfigured:
                raise
            except OpenRouterError as exc:
                log.warning("Could not build the journal description of work-history entry %d: %s", role.id, exc)
                warnings.append(f"The description could not be rebuilt from your journal right now ({exc}).")
            else:
                if context is None:
                    role.journal_failed_hash = target_hash
                    warnings.append(
                        "No description built from your journal passed the truthfulness check; "
                        "it will be tried again once your notes change."
                    )
                else:
                    role.journal_context, role.journal_hash = context, target_hash
                    role.journal_failed_hash = None
    session.commit()
    return warnings


def refresh_stale_journals(session: Session, roles: Iterable[WorkHistoryEntry], service: OpenRouterService) -> list[str]:
    """``refresh_journal`` every role of ``roles`` whose journal is stale; their warnings,
    prefixed with the role."""
    warnings: list[str] = []
    for role in roles:
        if role.kind == WorkHistoryEntry.KIND_JOB and is_stale(role):
            label = f"{role.role} @ {role.employer}" if role.employer else role.role
            warnings += [f"journal of {label}: {w}" for w in refresh_journal(session, role, service)]
    return warnings


# --- Activity -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class JournalActivity:
    count: int
    """Notes in the journal."""
    last_on: date | None
    """The day of the latest note (its ``logged_on``, so a backfilled note counts for its own day)."""


def activity(session: Session, role_ids: Iterable[int]) -> dict[int, JournalActivity]:
    """Note count and day of the latest note per role (roles without notes are left out)."""
    ids = list(role_ids)
    if not ids:
        return {}
    rows = session.execute(
        select(WorkJournalEntry.work_history_id, func.count(), func.max(WorkJournalEntry.logged_on))
        .where(WorkJournalEntry.work_history_id.in_(ids))
        .group_by(WorkJournalEntry.work_history_id)
    )
    return {role_id: JournalActivity(count, last_on) for role_id, count, last_on in rows}


def is_current_position(role: WorkHistoryEntry, today: date | None = None) -> bool:
    """A position held now: started, with no end date (what the Employment tab lists)."""
    return role.kind == WorkHistoryEntry.KIND_JOB and role.date_end is None and role.date_start <= (today or date.today())


def is_overdue(role: WorkHistoryEntry, last_on: date | None, today: date | None = None) -> bool:
    """A current position whose latest note is dated ``OVERDUE_AFTER`` or more before ``today``
    (with no notes: added to the app that long ago). The note's own day counts, not when it was
    saved: backfilling last month does not cover this week."""
    today = today or date.today()
    if not is_current_position(role, today):
        return False
    since = last_on or (role.created_at.date() if role.created_at else today)
    return today - since >= OVERDUE_AFTER


def overdue_role_ids(session: Session, today: date | None = None) -> list[int]:
    """Ids of the current positions without a journal note dated within ``OVERDUE_AFTER``."""
    today = today or date.today()
    roles = session.scalars(
        select(WorkHistoryEntry).where(
            WorkHistoryEntry.kind == WorkHistoryEntry.KIND_JOB,
            WorkHistoryEntry.date_end.is_(None),
            WorkHistoryEntry.date_start <= today,
        )
    ).all()
    stats = activity(session, [r.id for r in roles])
    return [r.id for r in roles if is_overdue(r, stats[r.id].last_on if r.id in stats else None, today)]
