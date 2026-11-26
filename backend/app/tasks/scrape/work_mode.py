"""Best-effort work mode (remote / hybrid / office) extraction shared by every scraper source.

A parsed work mode is one of ``WORK_MODES`` (stored in ``job_parse_results.work_mode``):

- ``"remote"``: the job can be done fully remotely,
- ``"hybrid"``: part remote, part in the office (also when a text offers both remote and
  office work, e.g. "Warszawa / hybrydowo / zdalnie"),
- ``"office"``: on-site only.

``work_mode_from_text`` scans plain text (a location line or a job description, Polish or
English), ``work_mode_from_jobposting`` reads a schema.org ``JobPosting.jobLocationType``.
Source modules may define a ``parse_work_mode(html) -> str | None`` hook built on these; the
parse task falls back to ``work_mode_from_text(description)`` for sources that do not.
"""

from __future__ import annotations

import re

REMOTE = "remote"
HYBRID = "hybrid"
OFFICE = "office"
WORK_MODES = (REMOTE, HYBRID, OFFICE)

_NEGATED_REMOTE = re.compile(
    r"(?i)(\bno\s+remote|\bnot\s+(a\s+)?(fully\s+)?remote|\bnon-?remote|"
    r"\b(bez|brak|nie\s+ma|nie\s+oferujemy)\s+(możliwości\s+)?(pracy\s+)?zdaln\w*)"
)
_PATTERNS = (
    (HYBRID, re.compile(r"(?i)(hybryd|\bhybrid)")),
    (
        REMOTE,
        re.compile(r"(?i)(\bremote|zdaln|\bhome[\s-]office|work(ing)?\s+from\s+home|\bwfh\b|telecommut|\bfull[\s-]?remote)"),
    ),
    (
        OFFICE,
        re.compile(
            r"(?i)(\bon[\s-]?site\b|\bonsite\b|stacjonarn|\bin[\s-](the\s+|our\s+)?office\b|\boffice[\s-]based\b|"
            r"\bw\s+biurze\b|\bz\s+biura\b|\bfrom\s+(the\s+|our\s+)?office\b)"
        ),
    ),
)


def work_modes_in(text: str | None) -> set[str]:
    """Every work mode ``text`` mentions (negated mentions such as "no remote" excluded)."""
    if not text:
        return set()
    text = _NEGATED_REMOTE.sub(" ", text)
    return {mode for mode, pattern in _PATTERNS if pattern.search(text)}


def work_mode_from_text(text: str | None) -> str | None:
    """The work mode stated in ``text``; ``None`` when it states none. A text naming both
    remote and office work (or hybrid work explicitly) is ``"hybrid"``."""
    modes = work_modes_in(text)
    if HYBRID in modes or {REMOTE, OFFICE} <= modes:
        return HYBRID
    if REMOTE in modes:
        return REMOTE
    if OFFICE in modes:
        return OFFICE
    return None


def work_mode_from_jobposting(ld: dict | None) -> str | None:
    """``"remote"`` when a schema.org ``JobPosting`` is ``jobLocationType: TELECOMMUTE``;
    ``None`` otherwise (a ``jobLocation`` alone does not say the job is on-site)."""
    kind = (ld or {}).get("jobLocationType")
    kinds = kind if isinstance(kind, list) else [kind]
    if any(isinstance(k, str) and k.strip().upper() == "TELECOMMUTE" for k in kinds):
        return REMOTE
    return None
