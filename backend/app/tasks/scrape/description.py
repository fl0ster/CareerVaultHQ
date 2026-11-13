"""Job description extraction.

Each scraper module in ``app.tasks.scrape.sources`` may declare how to turn one of its
job links into a plain-text description:

    DOMAINS = ("example.com")                 # hostnames (suffix match) it owns
    def parse_description(html, url) -> str    # for server-rendered pages, or
    def fetch_description(url) -> str          # when an API is better than HTML

``fetch_description(url)`` finds the owning module by hostname, calls its parser, and
falls back to generic extraction (JSON-LD JobPosting, common containers, cleaned body
text) when the module returns nothing usable.
"""

from __future__ import annotations

import logging
from types import ModuleType
from urllib.parse import urlparse

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