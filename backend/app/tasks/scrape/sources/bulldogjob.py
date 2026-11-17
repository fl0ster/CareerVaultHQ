"""BulldogJob scraper: fetches remote backend/fullstack/mobile/gamedev offers from bulldogjob.pl.

Both the listing and the offer pages are Next.js apps; the data is read from the
``__NEXT_DATA__`` JSON blob.
"""

from __future__ import annotations

import json

import httpx
from bs4 import BeautifulSoup

from app.tasks.scrape._helpers import HEADERS
from app.tasks.scrape.sources._helpers import html_to_text, join_fields

NAME = "BulldogJob"
BASE_URL = "https://bulldogjob.pl"
URL = f"{BASE_URL}/companies/jobs/s/city,Remote/role,fullstack,mobile,backend,gamedev"
DOMAINS = ("bulldogjob.pl", "bulldogjob.com")

# The listing shows 50 offers per page; pages are fetched until totalCount is
# reached or a page comes back with no new offers. The cap guards against loops.
MAX_PAGES = 20


def _next_data(html: str) -> dict:
    """``props.pageProps`` of a page's ``__NEXT_DATA__`` (empty dict when missing/broken)."""
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return {}
    try:
        data = json.loads(script.string)
    except ValueError:
        return {}
    return (data.get("props") or {}).get("pageProps") or {}


def parse_page(html: str) -> tuple[list[dict], int]:
    """Return (offers, total_count) of one listing page."""
    props = _next_data(html)
    return props.get("jobs") or [], props.get("totalCount") or 0


def parse_jobs(html: str, seen: set[str] | None = None) -> list[dict]:
    """Extract job links from one listing page, skipping ids already in ``seen``."""
    seen = set() if seen is None else seen
    offers, _ = parse_page(html)
    jobs: list[dict] = []
    for o in offers:
        job_id = o.get("id")
        if not o.get("position") or not job_id or str(job_id) in seen:
            continue
        seen.add(str(job_id))
        jobs.append({"link": f"{BASE_URL}/companies/jobs/{job_id}"})
    return jobs


def fetch_jobs() -> list[dict]:
    jobs: list[dict] = []
    seen: set[str] = set()
    for page in range(1, MAX_PAGES + 1):
        page_url = URL if page == 1 else f"{URL}/page,{page}"
        resp = httpx.get(page_url, headers=HEADERS, follow_redirects=True, timeout=30)
        resp.raise_for_status()

        _, total = parse_page(resp.text)
        new = parse_jobs(resp.text, seen)
        jobs.extend(new)
        if not new or len(seen) >= total:
            break
    return jobs


def _job(html: str) -> dict:
    """The job object of an offer page."""
    return (_next_data(html).get("data") or {}).get("job") or {}


def _salary(s: dict | None) -> str:
    if not s or s.get("hidden"):
        return ""
    amount = s.get("money")
    if not amount and (s.get("minValue") or s.get("maxValue")):
        amount = f"{s.get('minValue')}-{s.get('maxValue')}"
    if not amount:
        return ""
    return f"{amount} {s.get('currency') or ''} / {s.get('timeframe') or ''}".strip()


def parse_description(html: str) -> str:
    """Plain-text description of a single offer page."""
    job = _job(html)
    if not job:
        return ""

    contracts = []
    for flag, name, key in (
        ("contractB2b", "B2B", "b2bSalary"),
        ("contractEmployment", "Employment contract", "employmentSalary"),
        ("contractOther", "Other", "otherSalary"),
    ):
        if job.get(flag):
            sal = _salary(job.get(key))
            contracts.append(f"{name} ({sal})" if sal else name)

    cities: list[str] = []
    for loc in job.get("locations") or []:
        place = loc.get("location") or {}
        city = place.get("cityEn") or place.get("cityPl")
        if city and city not in cities:
            cities.append(city)

    benefits = [
        (b.get("name") or b.get("text")) if isinstance(b, dict) else str(b)
        for b in job.get("benefits") or []
    ]

    return join_fields(
        [
            ("Title", job.get("position")),
            ("Company", (job.get("company") or {}).get("name")),
            ("Level", job.get("experienceLevel")),
            (
                "Minimum Experience",
                f"{job['minExperienceInYears']} years" if job.get("minExperienceInYears") else "",
            ),
            ("Work Mode", job.get("workModes") or ("remote" if job.get("remote") else "")),
            ("Work From", job.get("workFrom")),
            ("Location", cities),
            ("Working Time", job.get("employmentType")),
            ("Employment", contracts),
            ("Main Technology", job.get("mainTechnology")),
            ("Technologies", job.get("technologyTags")),
            ("Description:", html_to_text(job.get("details"))),
            ("Requirements:", html_to_text(job.get("requirements"))),
            ("Recruitment Process:", html_to_text(job.get("recruitmentProcess"))),
            ("Benefits", [b for b in benefits if b]),
        ]
    )


def parse_title(html: str) -> str:
    """Job title of a single offer page (``job.position``; falls back to the ``<h1>``)."""
    title = _job(html).get("position")
    if title:
        return str(title).strip()
    h1 = BeautifulSoup(html, "html.parser").find("h1")
    return h1.get_text(" ", strip=True) if h1 else ""


def parse_company(html: str) -> str:
    """Hiring company of a single offer page (``job.company.name``)."""
    name = (_job(html).get("company") or {}).get("name")
    return str(name).strip() if name else ""
