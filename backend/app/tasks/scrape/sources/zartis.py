"""Zartis scraper: fetches job listings from zartis.com/careers (a Lever job board embed)."""

from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from app.tasks.scrape._helpers import HEADERS
from app.tasks.scrape.sources._helpers import (
    format_jobposting,
    html_to_text,
    jsonld_jobposting,
)

NAME = "Zartis"
URL = "https://www.zartis.com/careers/"
DOMAINS = ("zartis.com", "jobs.lever.co")

_TITLE_SUFFIX = re.compile(r"^\s*Zartis\s*-\s*")


def parse_jobs(html: str) -> list[dict]:
    """Extract job links from the careers page HTML."""
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict] = []
    seen: set[str] = set()

    # Each job listing is a <li class="lever-job"> with an <a class="lever-job-apply"> link
    for li in soup.find_all("li", class_="lever-job"):
        a = li.find("a", class_="lever-job-apply", href=True)
        if not a:
            continue
        link = a["href"].strip()
        if not link or link in seen:
            continue
        seen.add(link)
        jobs.append({"link": link})

    return jobs


def fetch_jobs() -> list[dict]:
    resp = httpx.get(URL, headers=HEADERS, follow_redirects=True, timeout=30)
    resp.raise_for_status()
    return parse_jobs(resp.text)


def parse_description(html: str) -> str:
    """Plain-text description of a single Lever job page (used by
    ``description.fetch_description``): the schema.org JobPosting when present,
    otherwise the ``data-qa="job-description"`` section."""
    ld = jsonld_jobposting(html)
    if ld:
        text = format_jobposting(ld)
        if text.strip():
            return text
    soup = BeautifulSoup(html, "html.parser")
    el = soup.find("div", attrs={"data-qa": "job-description"})
    return html_to_text(el) if el else ""


def parse_title(html: str) -> str:
    """Job title of a single job page (the posting headline; falls back to the
    JSON-LD JobPosting, then to ``<title>``)."""
    soup = BeautifulSoup(html, "html.parser")
    headline = soup.find("div", class_="posting-headline")
    h2 = headline.find("h2") if headline else None
    if h2 and h2.get_text(strip=True):
        return h2.get_text(" ", strip=True)

    ld = jsonld_jobposting(html)
    if ld and (ld.get("title") or ld.get("name")):
        return str(ld.get("title") or ld.get("name")).strip()

    title = soup.find("title")
    if not title:
        return ""

    # "Zartis - <job title>"
    result = _TITLE_SUFFIX.sub("", title.get_text(" ", strip=True)).strip()
    if result:
        return result

    # TODO: apply LLM to figure this out
    return ""


def parse_company(html: str) -> str:
    """Hiring company of a single job page (the JSON-LD ``hiringOrganization``;
    Zartis hires for itself, so falls back to ``NAME``)."""
    ld = jsonld_jobposting(html)
    org = ld.get("hiringOrganization") if ld else None
    name = org.get("name") if isinstance(org, dict) else org
    if isinstance(name, str) and name.strip():
        return name.strip()
    return NAME
