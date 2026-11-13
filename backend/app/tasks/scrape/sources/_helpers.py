"""Shared helpers for scraper source modules (HTTP headers, HTML -> text rendering,
schema.org JobPosting handling). Ported from the standalone scraper scripts."""

from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup, NavigableString


def html_to_text(value) -> str:
    """Collapse an HTML fragment (or already-plain text) to newline-separated text."""
    if not value:
        return ""
    if isinstance(value, BeautifulSoup) or hasattr(value, "get_text"):
        return value.get_text(separator="\n", strip=True)
    return BeautifulSoup(str(value), "html.parser").get_text(separator="\n", strip=True)


_BLOCK_TAGS = {
    "p", "div", "section", "article", "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6",
    "table", "tr", "blockquote", "pre", "hr", "header", "footer",
}  # fmt: skip


def html_to_blocks(fragment: str) -> str:
    """Render rich-text HTML to lines, keeping inline markup (<strong>, <span>)
    on the same line and turning list items into '- ' bullets."""
    soup = BeautifulSoup(fragment or "", "html.parser")
    lines: list[list[str]] = [[]]

    def walk(node):
        for child in node.children:
            if isinstance(child, NavigableString):
                text = str(child)
                if text.strip():
                    lines[-1].append(text)
                continue
            name = getattr(child, "name", None)
            if name in ("script", "style"):
                continue
            if name == "br":
                lines.append([])
            elif name in _BLOCK_TAGS:
                lines.append(["- "] if name == "li" else [])
                walk(child)
                lines.append([])
            else:
                walk(child)

    walk(soup)
    out = []
    for parts in lines:
        text = re.sub(r"\s+", " ", "".join(parts)).strip()
        if text == "-":
            continue
        if text:
            out.append(text)
    return "\n".join(out)


def join_fields(fields: list[tuple[str, object]]) -> str:
    """Render (label, value) pairs as 'Label: value' lines, skipping empties.
    Lists are comma-joined; a label ending in ':' is rendered as a block and an
    empty label emits the value as-is."""
    lines = []
    for label, value in fields:
        if isinstance(value, list | tuple):
            value = ", ".join(str(v) for v in value if v)
        if value is None or value == "":
            continue
        value = str(value).strip()
        if not value:
            continue
        if not label:
            lines.append(value)
        elif label.endswith(":"):
            lines.append(f"{label}\n{value}")
        else:
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


def jsonld_jobposting(html: str) -> dict | None:
    """Return the first schema.org JobPosting object embedded in the page."""
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (TypeError, ValueError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict) and "@graph" in item:
                items.extend(g for g in item["@graph"] if isinstance(g, dict))
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item
    return None


def _name(value) -> str:
    """Name of a schema.org thing, whether given as a string or an object."""
    if isinstance(value, dict):
        return value.get("name") or value.get("@id") or ""
    if isinstance(value, list):
        return ", ".join(filter(None, (_name(v) for v in value)))
    return str(value) if value else ""


def _jsonld_location(ld: dict) -> str:
    parts = []
    locations = ld.get("jobLocation") or []
    if isinstance(locations, dict):
        locations = [locations]
    for loc in locations:
        if not isinstance(loc, dict):
            continue
        addr = loc.get("address") or {}
        if isinstance(addr, dict):
            country = addr.get("addressCountry")
            piece = ", ".join(
                filter(
                    None,
                    (
                        addr.get("addressLocality"),
                        addr.get("addressRegion"),
                        country if isinstance(country, str) else _name(country),
                    ),
                )
            )
        else:
            piece = str(addr)
        if piece:
            parts.append(piece)
    req = ld.get("applicantLocationRequirements")
    if req:
        parts.append("applicants from: " + _name(req))
    if ld.get("jobLocationType"):
        parts.append(str(ld["jobLocationType"]))
    return "; ".join(dict.fromkeys(parts))


def _jsonld_salary(ld: dict) -> str:
    sal = ld.get("baseSalary")
    if not isinstance(sal, dict):
        return ""
    val = sal.get("value")
    cur = sal.get("currency") or ""
    if isinstance(val, dict):
        lo, hi, unit = val.get("minValue"), val.get("maxValue"), val.get("unitText") or ""
        amount = f"{lo}-{hi}" if lo and hi else str(lo or hi or val.get("value") or "")
        return f"{amount} {cur} / {unit}".strip() if amount else ""
    return f"{val} {cur}".strip() if val else ""


def format_jobposting(ld: dict) -> str:
    """Render a schema.org JobPosting as plain text."""
    return join_fields(
        [
            ("Title", ld.get("title") or ld.get("name")),
            ("Company", _name(ld.get("hiringOrganization"))),
            ("Location", _jsonld_location(ld)),
            ("Employment Type", ld.get("employmentType")),
            ("Salary", _jsonld_salary(ld)),
            ("Posted", str(ld.get("datePosted") or "")[:10]),
            ("Description:", html_to_text(ld.get("description"))),
        ]
    )


def parse_heading_sections(container, heading: str = "h2") -> str:
    """Render a server-rendered content block laid out as heading + content
    (paragraphs, lists) into "Heading:\\n- bullet" text. Content before the
    first heading is emitted as-is; list items become "- " bullets."""
    if container is None:
        return ""
    sections: list[tuple[str, list[str]]] = [("", [])]

    def render(el) -> str:
        if getattr(el, "name", None) in ("ul", "ol"):
            return "\n".join(
                f"- {li.get_text(' ', strip=True)}"
                for li in el.find_all("li")
                if li.get_text(strip=True)
            )
        if getattr(el, "name", None) is None:
            return str(el).strip()
        if el.find(["ul", "ol"]):
            parts = []
            for child in el.children:
                text = str(child).strip() if getattr(child, "name", None) is None else render(child)
                if text:
                    parts.append(text)
            return "\n".join(parts)
        return el.get_text("\n", strip=True)

    for el in container.children:
        name = getattr(el, "name", None)
        if name == heading:
            sections.append((el.get_text(" ", strip=True), []))
            continue
        text = render(el)
        if text:
            sections[-1][1].append(text)

    out = []
    for title, parts in sections:
        content = "\n".join(parts)
        if not content:
            continue
        out.append(f"{title}:\n{content}" if title else content)
    return "\n\n".join(out)
