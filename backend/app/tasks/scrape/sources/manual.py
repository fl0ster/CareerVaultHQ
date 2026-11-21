"""Jobs added by hand through ``POST /api/jobs/manual``.

Not a real scraper: ``fetch_jobs`` finds nothing (the source row is created disabled, see
``sync_sources``). The endpoint stores the entered fields as a JSON document in
``jobs.html`` and the ``parse_*`` hooks read them back, so manual jobs go through the same
parse -> evaluate pipeline as scraped ones.
"""

from __future__ import annotations

import json

NAME = "Manual"
URL = "manual://"


def to_html(title: str, company: str, description: str) -> str:
    return json.dumps({"title": title, "company": company, "description": description})


def _field(html: str, field: str) -> str:
    try:
        data = json.loads(html)
    except ValueError:
        return ""
    value = data.get(field) if isinstance(data, dict) else None
    return value.strip() if isinstance(value, str) else ""


def fetch_jobs() -> list[dict]:
    return []


def parse_title(html: str) -> str:
    return _field(html, "title")


def parse_company(html: str) -> str:
    return _field(html, "company")


def parse_description(html: str) -> str:
    return _field(html, "description")
