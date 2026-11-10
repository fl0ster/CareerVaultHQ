"""Job scraping as a background (RQ) job.

Discovers scraper modules in ``app.tasks.scrape.sources`` and runs them, collecting
every scraped job. The return value is stored as the RQ job result.
"""

from __future__ import annotations

import logging
from typing import Any

from app.tasks.scrape.sources import get_available_sources, load_source

log = logging.getLogger(__name__)


def run_source(name: str) -> dict[str, Any]:
    """Run a single scraper source. Never raises; failures are reported in the result."""
    log.info("=== Running scraper: %s ===", name)
    try:
        module = load_source(name)
        jobs = module.fetch_jobs()
    except Exception as exc:  # noqa: BLE001 - one broken source must not stop the others
        log.exception("Scraper %r failed", name)
        return {"source": name, "ok": False, "error": f"{type(exc).__name__}: {exc}", "jobs": []}
    log.info("Scraper %s returned %d jobs", name, len(jobs))
    return {"source": name, "ok": True, "error": None, "jobs": jobs}


def scrape(source: str | None = None) -> dict[str, Any]:
    """Scrape one source (``source``) or all available sources (``None``).

    Returns::

        {
            "sources": [{"source", "ok", "error", "jobs"}, ...],
            "failed": ["<source name>", ...],
            "jobs": [{"title", "link", "date_added", "source"}, ...],
            "count": <number of scraped jobs>,
        }
    """
    available = get_available_sources()
    if source is not None:
        if source not in available:
            raise ValueError(
                f"source {source!r} is not available; available: {', '.join(available)}"
            )
        names = [source]
    else:
        names = available

    results = [run_source(name) for name in names]
    jobs = [
        {**job, "source": result["source"]} for result in results for job in result["jobs"]
    ]
    return {
        "sources": results,
        "failed": [r["source"] for r in results if not r["ok"]],
        "jobs": jobs,
        "count": len(jobs),
    }
