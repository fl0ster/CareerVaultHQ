"""NoFluffJobs scraper: fetches mobile offers via the nofluffjobs.com search API.

Offer pages are Angular apps; their data is read from the ``serverApp-state`` JSON blob.
"""

from __future__ import annotations

import json

import httpx
from bs4 import BeautifulSoup

from app.tasks.scrape._helpers import HEADERS
from app.tasks.scrape.sources._helpers import html_to_text, join_fields

NAME = "NoFluffJobs"
BASE_URL = "https://nofluffjobs.com"
URL = f"{BASE_URL}/pl/praca-zdalna/mobile"
API_URL = f"{BASE_URL}/api/search/posting"
DOMAINS = ("nofluffjobs.com",)

_PARAMS = {"salaryCurrency": "PLN", "salaryPeriod": "month", "region": "pl"}
_PAYLOAD = {"criteriaSearch": {"category": ["mobile"]}}


def parse_jobs(data: dict) -> list[dict]:
    """Extract job links from the search API response."""
    jobs: list[dict] = []
    seen: set[str] = set()
    for p in data.get("postings") or []:
        suffix = p.get("url")
        if not p.get("title") or not suffix:
            continue
        link = f"{BASE_URL}/job/{suffix}"
        if link in seen:
            continue
        seen.add(link)
        jobs.append({"link": link})
    return jobs


def fetch_jobs() -> list[dict]:
    resp = httpx.post(API_URL, params=_PARAMS, json=_PAYLOAD, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return parse_jobs(resp.json())


def _posting(html: str) -> dict:
    """The posting object from an offer page's ``serverApp-state`` (empty dict if missing)."""
    script = BeautifulSoup(html, "html.parser").find("script", id="serverApp-state")
    if not script or not script.string:
        return {}
    try:
        data = json.loads(script.string)
    except ValueError:
        return {}
    for key, value in data.items():
        if "/posting/" in key and isinstance(value, dict):
            return value
    return {}


def _values(items: list | None) -> list[str]:
    return [i.get("value") for i in items or [] if i.get("value")]


def parse_description(html: str) -> str:
    """Plain-text description of a single offer page."""
    p = _posting(html)
    if not p:
        return ""
    ess = p.get("essentials") or {}
    salary = ess.get("convertedSalary") or ess.get("originalSalary") or {}
    salaries = []
    for name, val in (salary.get("types") or {}).items():
        r = (val or {}).get("range") or []
        if r:
            salaries.append(f"{name}: {r[0]}-{r[-1]} {salary.get('currency', '')} / {val.get('period', '')}")
    reqs = p.get("requirements") or {}
    benefits = p.get("benefits") or {}
    tasks = (p.get("specs") or {}).get("dailyTasks") or []
    return join_fields(
        [
            ("Title", p.get("title")),
            ("Company", (p.get("company") or {}).get("name")),
            ("Salary", salaries),
            ("Requirements (Must)", _values(reqs.get("musts"))),
            ("Requirements (Nice)", _values(reqs.get("nices"))),
            ("Requirements Description:", html_to_text(reqs.get("description"))),
            ("Daily Tasks:", "\n".join(f"- {t}" for t in tasks)),
            ("Description:", html_to_text((p.get("details") or {}).get("description"))),
            ("Benefits", benefits.get("benefits")),
            ("Office Perks", benefits.get("officePerks")),
        ]
    )


def parse_title(html: str) -> str:
    """Job title of a single offer page (posting title; falls back to the ``<h1>``)."""
    title = _posting(html).get("title")
    if title:
        return str(title).strip()
    h1 = BeautifulSoup(html, "html.parser").find("h1")
    return h1.get_text(" ", strip=True) if h1 else ""


def parse_company(html: str) -> str:
    """Hiring company of a single offer page (``company.name``)."""
    name = (_posting(html).get("company") or {}).get("name")
    return str(name).strip() if name else ""
