"""Job scraper sources: one plugin module per job board.

Adding a source
---------------
Drop a ``<key>.py`` file into this package (``key`` must not start with ``_``). It is
discovered automatically and mirrored into the ``scrape_sources`` table (see
``app.services.sources.sync_sources``) on the next ``GET /api/sources`` or scrape run, where
it can be enabled/disabled, prioritised and monitored. Removing the file retires the source:
its row is kept (jobs reference it) but marked broken with ``module_error``.

Each module must expose:

- ``NAME: str`` - human readable source name
- ``URL: str`` - listing page that is scraped
- ``fetch_jobs() -> list[dict]`` - returns dicts with ``link`` (details are parsed later)
- ``parse_title(html) -> str`` - job title of a job page
- ``parse_company(html) -> str`` - hiring company of a job page
- ``parse_description(html) -> str`` - plain-text description of a job page

(the ``parse_*`` hooks are called by ``app.tasks.parse.parse_job`` with the HTML stored on
the ``jobs`` row; ``parse_description`` is also used by ``app.tasks.scrape.description``).

Optional:

- ``DOMAINS: tuple[str, ...]`` - hostnames (suffix match) the module owns
- ``fetch_description(url) -> str`` - when an API is better than HTML
- ``parse_salary(html) -> dict | None`` - salary of a job page (see
  ``app.tasks.scrape.salary``); without it the parse task scans the parsed description
- ``parse_work_mode(html) -> str | None`` - ``"remote"``, ``"hybrid"`` or ``"office"`` (see
  ``app.tasks.scrape.work_mode``); without it the parse task scans the parsed description

``validate_source`` checks the contract and ``discover_sources`` reports every module with
its import/contract problems, so a broken file shows up as an unhealthy source instead of
breaking the whole scrape.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from types import ModuleType

REQUIRED_ATTRS = ("NAME", "URL")
"""Module-level string constants every source must define."""

REQUIRED_HOOKS = ("fetch_jobs", "parse_title", "parse_company", "parse_description")
"""Module-level callables every source must define."""


@dataclass(frozen=True)
class SourceInfo:
    """What discovery found out about one source module."""

    key: str
    """Module name; the stable identifier (``scrape_sources.key``)."""
    name: str
    """``NAME`` of the module (falls back to ``key`` when the module is broken)."""
    url: str | None
    """``URL`` of the module (``None`` when the module is broken)."""
    error: str | None = None
    """Import error or contract violations; ``None`` when the module is usable."""


def get_available_sources() -> list[str]:
    """Names of all scraper source modules in this package (sorted)."""
    return sorted(m.name for m in pkgutil.iter_modules(__path__) if not m.name.startswith("_"))


def load_source(name: str) -> ModuleType:
    if name not in get_available_sources():
        raise ValueError(f"unknown scrape source: {name!r}")
    return importlib.import_module(f"{__name__}.{name}")


def validate_source(module: ModuleType) -> list[str]:
    """Contract violations of ``module`` (empty when it is a valid source)."""
    problems: list[str] = []
    for attr in REQUIRED_ATTRS:
        value = getattr(module, attr, None)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"missing {attr}")
    for hook in REQUIRED_HOOKS:
        if not callable(getattr(module, hook, None)):
            problems.append(f"missing {hook}()")
    return problems


def discover_sources() -> list[SourceInfo]:
    """Import every source module and describe it, never raising: a module that fails to
    import or violates the contract is reported with ``error`` set."""
    infos: list[SourceInfo] = []
    for key in get_available_sources():
        try:
            module = importlib.import_module(f"{__name__}.{key}")
        except Exception as exc:  # noqa: BLE001 - a broken file must not hide the others
            error = f"{type(exc).__name__}: {exc}"
            infos.append(SourceInfo(key=key, name=key, url=None, error=error))
            continue
        problems = validate_source(module)
        name = getattr(module, "NAME", None)
        url = getattr(module, "URL", None)
        infos.append(
            SourceInfo(
                key=key,
                name=name if isinstance(name, str) and name.strip() else key,
                url=url if isinstance(url, str) and url.strip() else None,
                error="; ".join(problems) or None,
            )
        )
    return infos
