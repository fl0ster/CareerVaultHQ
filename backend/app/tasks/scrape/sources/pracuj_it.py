"""Pracuj IT scraper: fetches fully remote backend/mobile/fullstack/gamedev offers from
it.pracuj.pl.

Both the listing and the offer pages are Next.js apps (Pracuj Group, same format as
theprotocol.it); the data is read from the react-query state in ``__NEXT_DATA__``.
"""

from __future__ import annotations

import json
import re

import httpx
from bs4 import BeautifulSoup

from app.tasks.scrape._helpers import HEADERS
from app.tasks.scrape.sources._helpers import join_fields, parse_pracuj_sections

NAME = "Pracuj IT"
# wm=home-office -> fully remote; its=<specialisations>
URL = "https://it.pracuj.pl/praca?wm=home-office&its=backend,mobile,fullstack,gamedev"
DOMAINS = ("pracuj.pl",)

PAGE_SIZE = 50
MAX_PAGES = 20

# The specialisation filter is loose; drop obvious non-dev roles (PL + EN).
_TITLE_EXCLUDE_RE = re.compile(
    r"tester|test(ing)? engineer|automation|qa\b|quality|dan(e|ych)|data|analityk|analyst|"
    r"administrator|admin\b|wsparci|support|helpdesk|service desk|wdro[zż]e|consultant|"
    r"konsultant|ml engineer|machine learning|\bai engineer|scientist|devops|sre\b|security|"
    r"bezpiecze|manager|kierownik|scrum|product owner|sap\b|salesforce|scala|embedded|"
    r"sta[zż]|intern|junior|m[łl]odsz",
    re.I,
)


def is_relevant_title(title: str) -> bool:
    return not _TITLE_EXCLUDE_RE.search(title)


def _query_data(html: str, *keys: str) -> dict:
    """The first react-query result in ``__NEXT_DATA__`` that has all of ``keys``."""
    script = BeautifulSoup(html, "html.parser").find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return {}
    try:
        data = json.loads(script.string)
    except ValueError:
        return {}
    props = (data.get("props") or {}).get("pageProps") or {}
    for q in (props.get("dehydratedState") or {}).get("queries") or []:
        state = (q.get("state") or {}).get("data")
        if isinstance(state, dict) and all(k in state for k in keys):
            return state
    return {}


def parse_page(html: str) -> tuple[list[dict], int | None]:
    """Return (offer groups, total count) of one listing page."""
    state = _query_data(html, "groupedOffers")
    return state.get("groupedOffers") or [], state.get("groupedOffersTotalCount")


def parse_jobs(html: str, seen: set[str] | None = None) -> list[dict]:
    """Extract relevant job links from one listing page, skipping links already in ``seen``."""
    seen = set() if seen is None else seen
    groups, _ = parse_page(html)
    jobs: list[dict] = []
    for g in groups:
        title = (g.get("jobTitle") or "").strip()
        offers = g.get("offers") or []
        link = offers[0].get("offerAbsoluteUri") if offers else None
        if not title or not link or link in seen:
            continue
        seen.add(link)
        if not is_relevant_title(title):
            continue
        jobs.append({"link": link})
    return jobs


def fetch_jobs() -> list[dict]:
    jobs: list[dict] = []
    seen: set[str] = set()
    with httpx.Client(headers=HEADERS, timeout=60, follow_redirects=True) as client:
        for page in range(1, MAX_PAGES + 1):
            resp = client.get(URL if page == 1 else f"{URL}&pn={page}")
            resp.raise_for_status()
            groups, total = parse_page(resp.text)
            if not groups:
                break
            jobs.extend(parse_jobs(resp.text, seen))
            if total is not None and page * PAGE_SIZE >= total:
                break
    return jobs


def _offer(html: str) -> dict:
    """The job offer object of an offer page."""
    return _query_data(html, "sections", "attributes")


def _names(items) -> list[str]:
    out = []
    for i in items or []:
        if isinstance(i, dict):
            out.append(i.get("name") or i.get("text") or (i.get("label") or {}).get("text") or "")
        else:
            out.append(str(i))
    return [o for o in out if o]


def _label(value) -> str:
    """Text of a field that is either a plain string or a nested ``{"name": ...}`` object."""
    while isinstance(value, dict):
        value = value.get("name") or value.get("shortForm") or value.get("code")
    return str(value or "")


def _contracts(employment: dict) -> list[str]:
    out = []
    for c in employment.get("typesOfContracts") or []:
        sal = c.get("salary") or {}
        name = c.get("name") or ""
        if sal and (sal.get("from") or sal.get("to")):
            currency = sal.get("currency") or {}
            currency = currency.get("code") if isinstance(currency, dict) else currency
            parts = [
                f"{sal.get('from')}-{sal.get('to')}",
                currency or sal.get("currencyCode") or "",
                _label(sal.get("salaryKind")) or sal.get("kindCode") or "",
            ]
            unit = _label(sal.get("timeUnit"))
            amount = " ".join(p for p in parts if p) + (f" / {unit}" if unit else "")
            out.append(f"{name} ({amount})")
        elif name:
            out.append(name)
    return out


def parse_description(html: str) -> str:
    """Plain-text description of a single offer page."""
    offer = _offer(html)
    if not offer:
        return ""
    attrs = offer.get("attributes") or {}
    employment = attrs.get("employment") or {}

    # Primary/secondary attributes (specialisations, technologies, languages, ...) reuse
    # the section renderer by wrapping each one as a section.
    attr_sections = [
        {"title": (a.get("label") or {}).get("text") or a.get("code"), "model": a.get("model")}
        for a in (offer.get("primaryAttributes") or []) + (offer.get("secondaryAttributes") or [])
        if a.get("model")
    ]
    workplaces = [w.get("displayAddress") for w in attrs.get("workplaces") or []]
    published = (offer.get("publicationDetails") or {}).get("lastPublishedUtc") or ""

    return join_fields(
        [
            ("Title", attrs.get("jobTitle")),
            ("Employer", attrs.get("displayEmployerName")),
            ("Categories", _names(attrs.get("categories"))),
            ("Location", [w for w in workplaces if w]),
            ("Fully Remote", "yes" if employment.get("entirelyRemoteWork") else ""),
            ("Work Modes", _names(employment.get("workModes"))),
            ("Position Levels", _names(employment.get("positionLevels"))),
            ("Work Schedules", _names(employment.get("workSchedules"))),
            ("Contracts", _contracts(employment)),
            ("Published", str(published)[:10]),
            ("Archived", "yes" if attrs.get("isArchive") or attrs.get("isWithdrawn") else ""),
            ("", parse_pracuj_sections(attr_sections)),
            ("", parse_pracuj_sections(offer.get("sections"))),
        ]
    )


def parse_title(html: str) -> str:
    """Job title of a single offer page (``attributes.jobTitle``; falls back to the ``<h1>``)."""
    title = (_offer(html).get("attributes") or {}).get("jobTitle")
    if title:
        return str(title).strip()
    h1 = BeautifulSoup(html, "html.parser").find("h1")
    return h1.get_text(" ", strip=True) if h1 else ""


def parse_company(html: str) -> str:
    """Hiring company of a single offer page (``attributes.displayEmployerName``)."""
    name = (_offer(html).get("attributes") or {}).get("displayEmployerName")
    return str(name).strip() if name else ""
