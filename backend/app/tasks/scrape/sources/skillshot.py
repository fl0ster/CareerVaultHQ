"""Skillshot scraper: fetches job listings from skillshot.pl (programming category)."""

from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from app.tasks.scrape.sources._helpers import HEADERS, html_to_text

NAME = "Skillshot"
BASE_URL = "https://www.skillshot.pl"
URL = f"{BASE_URL}/jobs?category=programowanie"
DOMAINS = ("skillshot.pl",)

_JOB_HREF = re.compile(r"^/jobs/\d+")
_USER_HREF = re.compile(r"^/users/\d+")


def parse_jobs(html: str) -> list[dict]:
    """Extract job links from the listing page HTML."""
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict] = []
    seen: set[str] = set()

    # Each job listing is an <a> tag whose href starts with /jobs/<id>
    for a in soup.find_all("a", href=_JOB_HREF):
        link = BASE_URL + a["href"]
        if link in seen:
            continue
        seen.add(link)
        jobs.append({"link": link})

    return jobs


def fetch_jobs() -> list[dict]:
    resp = httpx.get(URL, headers=HEADERS, follow_redirects=True, timeout=30)
    resp.raise_for_status()
    return parse_jobs(resp.text)


def parse_description(html: str, url: str) -> str:
    """Plain-text description of a single job page (used by ``description.fetch_description``)."""
    soup = BeautifulSoup(html, "html.parser")
    el = soup.find("div", id="job_presentation")
    return html_to_text(el) if el else ""


def parse_title(html: str, url: str) -> str:
    """Job title of a single job page (the ``<h1>``; falls back to ``<title>``)."""
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(" ", strip=True)
    title = soup.find("title")
    if not title:
        return ""

    # TODO: apply LLM to figure this out
    return ""


def parse_company(html: str, url: str) -> str:
    """Hiring company of a single job page (the ``/users/<id>`` link in the job header;
    falls back to ``<title>``)."""
    soup = BeautifulSoup(html, "html.parser")
    header = soup.find("div", id="job_presentation") or soup
    a = header.find("a", href=_USER_HREF)
    if a and a.get_text(strip=True):
        return a.get_text(" ", strip=True)
    title = soup.find("title")
    if not title:
        return ""
    
    # TODO: apply LLM to figure this out
    return ""
