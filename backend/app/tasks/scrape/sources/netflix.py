"""Netflix scraper: fetches remote job listings from Netflix Careers (an Eightfold board)."""

from __future__ import annotations

import json
import logging

import httpx
from bs4 import BeautifulSoup

from app.tasks.scrape._helpers import HEADERS
from app.tasks.scrape.sources._helpers import (
    format_jobposting,
    html_to_text,
    join_fields,
    jsonld_jobposting,
)

log = logging.getLogger(__name__)

NAME = "Netflix"
# Listing page: the first page of positions and the total count are embedded in the HTML
URL = (
    "https://explore.jobs.netflix.net/careers?location=Remote&pid=790315961316"
    "&domain=netflix.com&sort_by=relevance&triggerGoButton=false&triggerGoButton=true"
)
# Pagination API for the remaining pages
API_URL = "https://explore.jobs.netflix.net/api/apply/v2/jobs"
API_PARAMS = {
    "domain": "netflix.com",
    "location": "Remote",
    "pid": "790315961316",
    "sort_by": "relevance",
    "triggerGoButton": "true",
}
PAGE_SIZE = 10
DOMAINS = ("explore.jobs.netflix.net", "jobs.netflix.com")


def _smart_apply_data(html: str) -> dict:
    """The Eightfold ``smartApplyData`` JSON blob embedded in a careers page (``{}`` if absent)."""
    soup = BeautifulSoup(html, "html.parser")
    code_tag = soup.find("code", id="smartApplyData")
    if not code_tag:
        return {}
    try:
        data = json.loads(code_tag.string or "")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _links(positions: list[dict], seen: set[str]) -> list[dict]:
    jobs: list[dict] = []
    for p in positions:
        link = (p.get("canonicalPositionUrl") or "").strip()
        if not link or link in seen:
            continue
        seen.add(link)
        jobs.append({"link": link})
    return jobs


def parse_jobs(html: str) -> list[dict]:
    """Extract job links from the first listing page HTML (``smartApplyData`` positions)."""
    return _links(_smart_apply_data(html).get("positions") or [], set())


def fetch_jobs() -> list[dict]:
    resp = httpx.get(URL, headers=HEADERS, follow_redirects=True, timeout=30)
    resp.raise_for_status()

    data = _smart_apply_data(resp.text)
    total = int(data.get("count") or 0)
    initial = data.get("positions") or []
    seen: set[str] = set()
    jobs = _links(initial, seen)

    # Remaining pages via the API
    start = len(initial)
    while initial and start < total:
        params = {**API_PARAMS, "start": str(start), "num": str(PAGE_SIZE)}
        api_resp = httpx.get(API_URL, headers=HEADERS, params=params, follow_redirects=True, timeout=30)
        if api_resp.status_code != 200:
            log.warning("netflix API request failed with status %s", api_resp.status_code)
            break
        positions = api_resp.json().get("positions") or []
        if not positions:
            break
        jobs.extend(_links(positions, seen))
        start += len(positions)

    return jobs


def _position(html: str) -> dict:
    positions = _smart_apply_data(html).get("positions") or []
    return positions[0] if positions and isinstance(positions[0], dict) else {}


def parse_description(html: str) -> str:
    """Plain-text description of a single job page (used by ``description.fetch_description``):
    the Eightfold ``smartApplyData`` position, falling back to the schema.org JobPosting."""
    pos = _position(html)
    body = html_to_text(pos.get("job_description") or pos.get("description"))
    if not body:
        ld = jsonld_jobposting(html)
        return format_jobposting(ld) if ld else ""
    return join_fields(
        [
            ("Title", pos.get("name")),
            ("Location", pos.get("location")),
            ("Department", pos.get("department")),
            ("Description:", body),
        ]
    )


def parse_title(html: str) -> str:
    """Job title of a single job page (``smartApplyData`` position name; falls back to the
    JSON-LD JobPosting, then to ``<title>``)."""
    name = _position(html).get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()

    ld = jsonld_jobposting(html)
    if ld and (ld.get("title") or ld.get("name")):
        return str(ld.get("title") or ld.get("name")).strip()

    soup = BeautifulSoup(html, "html.parser")
    title = soup.find("title")
    if not title:
        return ""

    # "<job title> | <location> | Netflix"
    result = title.get_text(" ", strip=True).split("|")[0].strip()
    if result:
        return result

    # TODO: apply LLM to figure this out
    return ""


def parse_company(html: str) -> str:
    """Hiring company of a single job page (JSON-LD ``hiringOrganization``; Netflix hires
    for itself, so falls back to ``NAME``)."""
    ld = jsonld_jobposting(html)
    org = ld.get("hiringOrganization") if ld else None
    name = org.get("name") if isinstance(org, dict) else org
    if isinstance(name, str) and name.strip():
        return name.strip()
    return NAME
