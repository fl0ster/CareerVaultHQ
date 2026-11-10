"""Skillshot scraper: fetches job listings from skillshot.pl (programming category)."""

from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

NAME = "Skillshot"
BASE_URL = "https://www.skillshot.pl"
URL = f"{BASE_URL}/jobs?category=programowanie"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

_JOB_HREF = re.compile(r"^/jobs/\d+")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def parse_jobs(html: str) -> list[dict]:
    """Extract job listings from the listing page HTML."""
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict] = []
    seen: set[str] = set()

    # Each job listing is an <a> tag whose href starts with /jobs/<id>
    for a in soup.find_all("a", href=_JOB_HREF):
        title = a.get_text(strip=True)
        link = BASE_URL + a["href"]
        if not title or link in seen:
            continue
        seen.add(link)

        # Date is in a sibling <td> within the same <tr>
        date_added = ""
        tr = a.find_parent("tr")
        if tr:
            match = _DATE.search(tr.get_text(" ", strip=True))
            date_added = match.group(0) if match else ""

        jobs.append({"title": title, "link": link, "date_added": date_added})

    return jobs


def fetch_jobs() -> list[dict]:
    resp = httpx.get(URL, headers=HEADERS, follow_redirects=True, timeout=30)
    resp.raise_for_status()
    return parse_jobs(resp.text)
