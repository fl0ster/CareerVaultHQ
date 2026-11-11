"""Job scraper sources.

Each module in this package (not starting with ``_``) must expose:

- ``NAME: str`` - human readable source name
- ``URL: str`` - listing page that is scraped
- ``fetch_jobs() -> list[dict]`` - returns dicts with ``link`` (details are parsed later)

Optionally, to extract job descriptions (see ``app.tasks.scrape.description``):

- ``DOMAINS: tuple[str, ...]`` - hostnames (suffix match) the module owns
- ``parse_description(html, url) -> str`` and/or ``fetch_description(url) -> str``
"""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType


def get_available_sources() -> list[str]:
    """Names of all scraper source modules in this package (sorted)."""
    return sorted(m.name for m in pkgutil.iter_modules(__path__) if not m.name.startswith("_"))


def load_source(name: str) -> ModuleType:
    if name not in get_available_sources():
        raise ValueError(f"unknown scrape source: {name!r}")
    return importlib.import_module(f"{__name__}.{name}")
