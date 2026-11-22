"""Technology names: one comparison key per technology, without any technology list.

``technology_key`` only applies spelling rules that hold for any technology: case,
spacing and punctuation are ignored, a trailing version number is dropped and a ``.js`` /
``JS`` suffix is optional. So "React.js", "ReactJS", "react-js" and "React" share a key,
as do "Java 17" and "Java", but spellings that are genuinely different words ("Postgres"
vs "PostgreSQL", "k8s" vs "Kubernetes") stay apart. The extraction prompt asks the model
for each technology's usual name, which merges most of those on the job side.

A job's ``JobParseResult.technologies`` (each entry carries its ``key``) is checked
against ``WorkHistoryEntry.tech`` with plain set operations::

    from app.services.technologies import match_technologies

    match = match_technologies(parsed.technologies, [e.tech for e in work_history])
    match.matched, match.missing
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

_VERSION_SUFFIX = re.compile(r"\s+v?\d+(\.\d+)*(\.x)?\+?$")
"""Trailing version numbers ("Java 17", "Python 3.11", "Angular 15"); a space must precede
the version so names like "S3" or "EC2" are kept."""

_IGNORED = re.compile(r"[^\w+#]")
"""Everything but letters, digits, ``+`` and ``#`` (so "C", "C++" and "C#" stay apart)."""


def technology_key(name: str) -> str:
    """The comparison key of a technology name ("" for a blank name)."""
    name = name.strip().lower()
    name = _VERSION_SUFFIX.sub("", name) or name
    key = _IGNORED.sub("", name).replace("_", "")
    if key.endswith("js") and len(key) > 2:
        key = key[:-2]
    return key


def dedupe_technologies(names: Iterable[str]) -> list[dict[str, str]]:
    """``[{"name": <first spelling seen>, "key": technology_key(name)}, ...]`` with one
    entry per key, in input order."""
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for name in names:
        clean = " ".join(name.split())
        key = technology_key(clean)
        if key and key not in seen:
            seen.add(key)
            out.append({"name": clean, "key": key})
    return out


@dataclass(frozen=True)
class TechnologyMatch:
    matched: list[str]
    """Names of the job's technologies the candidate has used."""
    missing: list[str]
    """Names of the job's technologies absent from the work history."""

    @property
    def ratio(self) -> float | None:
        total = len(self.matched) + len(self.missing)
        return len(self.matched) / total if total else None


def match_technologies(job_technologies: Iterable[dict] | None, history_tech: Iterable[Iterable[str]]) -> TechnologyMatch:
    """Compare ``JobParseResult.technologies`` with the ``tech`` lists of the work history
    entries, by key."""
    known = {technology_key(name) for tech in history_tech for name in tech}
    matched: list[str] = []
    missing: list[str] = []
    for item in job_technologies or []:
        key = item.get("key") or technology_key(item.get("name", ""))
        (matched if key in known else missing).append(item.get("name") or key)
    return TechnologyMatch(matched, missing)
