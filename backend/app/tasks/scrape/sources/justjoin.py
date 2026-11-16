"""JustJoin scraper: fetches mobile and game development job listings from justjoin.it.

The listing is a Next.js app: each page embeds its offers in the React Server Components
payload, 50 per page. Requesting a page past the last one returns 404, so that is treated
as the end of the listing rather than an error. Offer pages embed the full offer object
(skills, salary, HTML body) in the same way.
"""

from __future__ import annotations

import re

import httpx

from app.tasks.scrape._helpers import HEADERS
from app.tasks.scrape.sources._helpers import (
    decode_rsc,
    html_to_blocks,
    join_fields,
    resolve_rsc_ref,
    rsc_object,
)

NAME = "JustJoin"
BASE_URL = "https://justjoin.it"
CATEGORIES = ("mobile", "game")
URL = f"{BASE_URL}/job-offers/all-locations/{CATEGORIES[0]}"
DOMAINS = ("justjoin.it",)
PAGE_SIZE = 50
MAX_PAGES = 20  # per category; only guards against an endless loop

# Titles worth keeping from this broad, multi-discipline board. Deliberately wide:
# the evaluation step does the real fit check.
_TITLE_RE = re.compile(
    r"react.?native|android|kotlin|unity|unreal|game|mobile|ios|flutter|"
    r"typescript|node|\.net|c#|csharp|backend|back.?end|full.?stack|fullstack|"
    r"software|developer|engineer|programmer|architect|tech(nical)? lead|staff",
    re.I,
)

# Titles to drop even if they match _TITLE_RE.
_TITLE_EXCLUDE_RE = re.compile(
    r"\b(qa|quality|test(er|ing)?|sales|account|recruit|marketing|support|"
    r"data (scientist|analyst|engineer)|machine learning|ml |ai engineer|"
    r"devops|sre|security|embedded|hardware|intern|junior|customer|"
    r"manager|designer|artist|writer|community|salesforce|sap|scala|"
    r"solutions? engineer|field engineer|demo engineer|enablement)\b",
    re.I,
)


def is_relevant_title(title: str) -> bool:
    return bool(_TITLE_RE.search(title)) and not _TITLE_EXCLUDE_RE.search(title)


def parse_offers(html: str) -> list[dict]:
    """The offer objects embedded in one listing page."""
    return rsc_object(decode_rsc(html), '{"offers":[').get("offers") or []


def parse_jobs(html: str, seen: set[str] | None = None) -> list[dict]:
    """Extract relevant job links from one listing page HTML (deduplicated by slug)."""
    seen = set() if seen is None else seen
    jobs: list[dict] = []
    for o in parse_offers(html):
        title = (o.get("title") or "").strip()
        slug = o.get("slug")
        if not title or not slug or slug in seen:
            continue
        seen.add(slug)
        if not is_relevant_title(title):
            continue
        jobs.append({"link": f"{BASE_URL}/job-offer/{slug}"})
    return jobs


def fetch_jobs() -> list[dict]:
    jobs: list[dict] = []
    seen: set[str] = set()
    with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        for category in CATEGORIES:
            listing_url = f"{BASE_URL}/job-offers/all-locations/{category}"
            for page in range(1, MAX_PAGES + 1):
                resp = client.get(listing_url, params={"page": page} if page > 1 else None)
                if resp.status_code == 404:
                    break  # past the last page
                resp.raise_for_status()

                offers = parse_offers(resp.text)
                jobs.extend(parse_jobs(resp.text, seen))
                if len(offers) < PAGE_SIZE:
                    break
    return jobs


def _rsc_offer(html: str) -> tuple[dict, str]:
    """The offer object embedded in an offer page, plus the decoded payload."""
    payload = decode_rsc(html)
    return rsc_object(payload, '{"offer":{"slug":').get("offer") or {}, payload


def _label(value) -> str:
    if isinstance(value, dict):
        return value.get("label") or value.get("value") or ""
    return value or ""


def _contracts(employment_types: list) -> list[str]:
    out = []
    for et in employment_types or []:
        if et.get("currencySource") == "conversion":
            continue  # same salary converted to other currencies
        name = _label(et.get("label")) or et.get("type") or ""
        lo, hi = et.get("from"), et.get("to")
        if lo or hi:
            gross = "gross" if et.get("gross") else "net"
            out.append(f"{name} ({lo}-{hi} {et.get('currency', '')} {gross} / {et.get('unit', '')})")
        elif name:
            out.append(name)
    return out


def _skills(items: list) -> list[str]:
    out = []
    for s in items or []:
        name = s.get("name") if isinstance(s, dict) else s
        level = s.get("level") if isinstance(s, dict) else None
        if name:
            out.append(f"{name} ({level}/5)" if level else name)
    return out


def parse_description(html: str) -> str:
    """Structured offer data plus the HTML body from the offer page's RSC payload
    (used by ``description.fetch_description``)."""
    offer, payload = _rsc_offer(html)
    if not offer:
        return ""
    return join_fields(
        [
            ("Title", offer.get("title")),
            ("Company", offer.get("companyName")),
            ("Level", _label(offer.get("experienceLevel"))),
            ("Work Mode", _label(offer.get("workplaceType"))),
            ("Working Time", _label(offer.get("workingTime"))),
            ("Location", [p for p in (offer.get("city"), offer.get("street")) if p and p != "-"]),
            ("Employment", _contracts(offer.get("employmentTypes"))),
            ("Required Skills", _skills(offer.get("requiredSkills"))),
            ("Nice To Have Skills", _skills(offer.get("niceToHaveSkills"))),
            ("Description:", html_to_blocks(resolve_rsc_ref(payload, offer.get("body")))),
        ]
    )


def parse_title(html: str) -> str:
    """Job title of a single offer page (the embedded offer's ``title``)."""
    offer, _ = _rsc_offer(html)
    title = offer.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()

    # TODO: apply LLM to figure this out
    return ""


def parse_company(html: str) -> str:
    """Hiring company of a single offer page (the embedded offer's ``companyName``)."""
    offer, _ = _rsc_offer(html)
    company = offer.get("companyName")
    if isinstance(company, str) and company.strip():
        return company.strip()

    # TODO: apply LLM to figure this out
    return ""
