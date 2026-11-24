"""Resolving the company name scraped from a job page to a canonical ``Company`` row.

Three tables are involved (see ``app.models``):

- ``companies`` - the canonical record (one row per real company)
- ``company_aliases`` - every spelling ever seen, mapped to its canonical row
- ``job_parse_results.company_id`` - points at the canonical row

``resolve_company(session, raw_name)`` runs a deliberately simple pipeline:

1. normalise the spelling (``normalize_company_name``)
2. look it up in ``company_aliases``
3. look it up in ``companies.normalized_name``
4. fuzzy match it against every canonical name and alias (``FUZZY_THRESHOLD``)
5. otherwise create a new canonical row

The raw spelling is always stored as an alias so the next identical spelling is resolved
by step 2. Duplicates are accepted at this stage; they can be merged by hand through
``company_aliases``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, CompanyAlias, ScrapeSource, WorkHistoryEntry

FUZZY_THRESHOLD = 0.85
"""Minimum ``similarity`` (0-1) for a fuzzy match to be accepted."""

FUZZY_MIN_LENGTH = 4
"""Normalised names shorter than this are never fuzzy matched; they must match exactly."""

MATCH_ALIAS = "alias"
"""``CompanyMatch.match_kind`` when the spelling was found in ``company_aliases``."""

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def normalize_company_name(raw: str) -> str:
    """Deterministic lookup key: accents stripped, casefolded, anything that is not a
    letter or digit collapsed to a single space.

    >>> normalize_company_name("  Techland Sp. z o.o. ")
    'techland sp z o o'
    """
    text = unicodedata.normalize("NFKD", raw)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("ł", "l").replace("Ł", "L").casefold()
    return _NON_ALNUM_RE.sub(" ", text).strip()


def similarity(a: str, b: str) -> float:
    """Similarity (0-1) between two normalised names."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


@dataclass(frozen=True)
class CompanyMatch:
    """Outcome of ``resolve_company``."""

    company: Company
    match_kind: str
    """``MATCH_ALIAS`` or one of ``CompanyAlias.MATCH_EXACT`` / ``MATCH_FUZZY`` / ``MATCH_NEW``."""
    similarity: float | None = None
    """Score of the fuzzy match when ``match_kind == "fuzzy"``."""
    created: bool = False
    """``True`` when the canonical ``Company`` row was created by this call."""


def _find_fuzzy(session: Session, normalized: str, threshold: float) -> tuple[int, float] | None:
    """``(company_id, score)`` of the closest canonical name or alias at or above
    ``threshold``, or ``None``."""
    if len(normalized) < FUZZY_MIN_LENGTH:
        return None
    candidates = session.execute(
        select(Company.id, Company.normalized_name).union_all(select(CompanyAlias.company_id, CompanyAlias.normalized_alias))
    ).all()
    best: tuple[int, float] | None = None
    for company_id, candidate in candidates:
        score = similarity(normalized, candidate)
        if score >= threshold and (best is None or score > best[1]):
            best = (company_id, score)
    return best


def find_company(session: Session, raw_name: str, *, threshold: float = FUZZY_THRESHOLD) -> Company | None:
    """Read-only counterpart of ``resolve_company``: the canonical ``Company`` that
    ``raw_name`` refers to (known alias, exact name, then closest fuzzy match), or ``None``.
    Nothing is added to the session."""
    normalized = normalize_company_name(raw_name or "")
    if not normalized:
        return None
    alias = session.scalar(select(CompanyAlias).where(CompanyAlias.normalized_alias == normalized))
    if alias is not None:
        return alias.company
    company = session.scalar(select(Company).where(Company.normalized_name == normalized))
    if company is not None:
        return company
    fuzzy = _find_fuzzy(session, normalized, threshold)
    return session.get(Company, fuzzy[0]) if fuzzy is not None else None


def resolve_company(
    session: Session,
    raw_name: str,
    *,
    source: ScrapeSource | None = None,
    threshold: float = FUZZY_THRESHOLD,
) -> CompanyMatch | None:
    """Map ``raw_name`` to its canonical ``Company``, adding rows to the session as needed
    (the caller commits). ``source`` is the scrape source the spelling was seen on and is
    recorded on the alias. Returns ``None`` when ``raw_name`` is empty after normalisation."""
    normalized = normalize_company_name(raw_name or "")
    if not normalized:
        return None

    alias = session.scalar(select(CompanyAlias).where(CompanyAlias.normalized_alias == normalized))
    if alias is not None:
        return CompanyMatch(alias.company, MATCH_ALIAS, alias.similarity)

    company = session.scalar(select(Company).where(Company.normalized_name == normalized))
    if company is not None:
        kind, score, created = CompanyAlias.MATCH_EXACT, None, False
    elif (fuzzy := _find_fuzzy(session, normalized, threshold)) is not None:
        company = session.get(Company, fuzzy[0])
        kind, score, created = CompanyAlias.MATCH_FUZZY, fuzzy[1], False
    else:
        company = Company(name=raw_name.strip(), normalized_name=normalized)
        session.add(company)
        kind, score, created = CompanyAlias.MATCH_NEW, None, True

    session.add(
        CompanyAlias(
            company=company,
            alias=raw_name.strip(),
            normalized_alias=normalized,
            match_kind=kind,
            similarity=score,
            source=source,
        )
    )
    session.flush()
    return CompanyMatch(company, kind, score, created)


def resolve_career_companies(session: Session, entries: list[WorkHistoryEntry]) -> dict[int, Company]:
    """``{entry_id: company}`` for the positions among ``entries``, resolving each employer
    with ``resolve_company``: an employer seen only in the career becomes a company too, so it
    can be tagged like any other. New companies and aliases are committed."""
    by_name: dict[str, Company | None] = {}
    matched: dict[int, Company] = {}
    added = False
    for entry in entries:
        if entry.kind != WorkHistoryEntry.KIND_JOB:
            continue
        key = normalize_company_name(entry.employer or "")
        if not key:
            continue
        if key not in by_name:
            match = resolve_company(session, entry.employer)
            by_name[key] = match.company if match else None
            # Anything but a known alias adds rows (an alias, maybe a company).
            added = added or (match is not None and match.match_kind != MATCH_ALIAS)
        if (company := by_name[key]) is not None:
            matched[entry.id] = company
    if added:
        session.commit()
    return matched
