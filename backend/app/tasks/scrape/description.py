"""Job description extraction.

Each scraper module in ``app.tasks.scrape.sources`` may declare how to turn one of its
job links into a plain-text description:

    DOMAINS = ("example.com",)                # hostnames (suffix match) it owns
    def parse_description(html) -> str         # for server-rendered pages, or
    def fetch_description(url) -> str          # when an API is better than HTML

``import_job(url, fetch_html)`` finds the owning module by hostname, calls its parsers, and
falls back to ``app.tasks.scrape.generic`` (JSON-LD JobPosting, common containers, cleaned
body text) for whatever the module leaves empty, or when no module owns the domain.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from types import ModuleType
from urllib.parse import urlparse

from app.tasks.scrape import generic
from app.tasks.scrape.sources import get_available_sources, load_source

log = logging.getLogger(__name__)

MIN_DESCRIPTION_CHARS = 100

_registry: list[tuple[tuple[str, ...], ModuleType]] | None = None


def _load_registry() -> list[tuple[tuple[str, ...], ModuleType]]:
    """Import every scraper module that declares ``DOMAINS`` and a description hook."""
    global _registry
    if _registry is not None:
        return _registry
    mods = []
    for name in get_available_sources():
        try:
            mod = load_source(name)
        except Exception:  # noqa: BLE001 - a broken source must not break extraction
            log.exception("could not import source %r", name)
            continue
        domains = getattr(mod, "DOMAINS", None)
        if domains and (hasattr(mod, "parse_description") or hasattr(mod, "fetch_description")):
            mods.append((tuple(d.lower() for d in domains), mod))
    _registry = mods
    return mods


def find_source(url: str) -> ModuleType | None:
    host = urlparse(url).netloc.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    best, best_len = None, 0
    for domains, mod in _load_registry():
        for d in domains:
            if (host == d or host.endswith("." + d)) and len(d) > best_len:
                best, best_len = mod, len(d)
    return best


@dataclass(frozen=True)
class ImportedJob:
    title: str
    company: str
    description: str
    source: str | None
    """``NAME`` of the source module owning the domain; ``None`` for unknown domains."""


def _call(module: ModuleType, hook: str, arg: str) -> str:
    fn = getattr(module, hook, None)
    if fn is None:
        return ""
    try:
        return (fn(arg) or "").strip()
    except Exception:  # noqa: BLE001 - a parser bug falls back to the generic parser
        log.exception("%s.%s failed", module.__name__, hook)
        return ""


def import_job(url: str, fetch_html: Callable[[str], str]) -> ImportedJob:
    """Fetch ``url`` and parse its title, company and description with the source module
    owning its domain; ``generic`` fills whatever that leaves empty (everything, for unknown
    domains). Stores nothing; raises whatever ``fetch_html`` raises."""
    module = find_source(url)
    html = fetch_html(url)
    values = {"title": "", "company": "", "description": ""}
    if module is not None:
        values["description"] = _call(module, "fetch_description", url)
        for field in values:
            if not values[field]:
                values[field] = _call(module, f"parse_{field}", html)
    if len(values["description"]) < MIN_DESCRIPTION_CHARS:
        values["description"] = _call(generic, "parse_description", html) or values["description"]
    for field in ("title", "company"):
        if not values[field]:
            values[field] = _call(generic, f"parse_{field}", html)
    source = getattr(module, "NAME", None) if module is not None else None
    return ImportedJob(source=source, **values)
