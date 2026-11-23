"""Naive, best-effort parser for job pages of boards no source module owns.

Used by ``description.import_job`` when the link's domain matches no scraper (or the
scraper leaves a field empty). Tries, in order: the schema.org ``JobPosting`` embedded in
the page, then ``<h1>`` / OpenGraph / ``<title>`` for the title and the main content block
(``<main>``, ``<article>``, ...) or the cleaned ``<body>`` for the description.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from app.tasks.scrape.sources._helpers import _name, format_jobposting, html_to_blocks, jsonld_jobposting

MAX_DESCRIPTION_CHARS = 20_000

_NOISE_TAGS = ("script", "style", "noscript", "svg", "nav", "header", "footer", "form", "iframe", "aside", "button")
_CONTENT_SELECTORS = (
    "[itemprop=description]",
    "#job-description",
    ".job-description",
    "main",
    "article",
    "[role=main]",
    "#content",
    ".content",
)
_MIN_CONTENT_CHARS = 200
_TITLE_SEPARATORS = re.compile(r"\s+[|\-–—]\s+")


def _meta(soup: BeautifulSoup, *names: str) -> str:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        content = tag.get("content") if tag else None
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""


def parse_title(html: str) -> str:
    ld = jsonld_jobposting(html)
    if ld and (ld.get("title") or ld.get("name")):
        return str(ld.get("title") or ld.get("name")).strip()
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(" ", strip=True)
    title = _meta(soup, "og:title", "twitter:title") or (soup.title.get_text(strip=True) if soup.title else "")
    # "Senior Dev | Acme Careers" -> "Senior Dev"
    return _TITLE_SEPARATORS.split(title, maxsplit=1)[0].strip()


def parse_company(html: str) -> str:
    ld = jsonld_jobposting(html)
    if ld:
        company = _name(ld.get("hiringOrganization")).strip()
        if company:
            return company
    return _meta(BeautifulSoup(html, "html.parser"), "og:site_name")


def parse_description(html: str) -> str:
    ld = jsonld_jobposting(html)
    if ld:
        text = format_jobposting(ld)
        if text.strip():
            return text[:MAX_DESCRIPTION_CHARS]
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_NOISE_TAGS):
        tag.decompose()
    container = None
    for selector in _CONTENT_SELECTORS:
        el = soup.select_one(selector)
        if el is not None and len(el.get_text(strip=True)) >= _MIN_CONTENT_CHARS:
            container = el
            break
    container = container or soup.body or soup
    return html_to_blocks(str(container))[:MAX_DESCRIPTION_CHARS]
