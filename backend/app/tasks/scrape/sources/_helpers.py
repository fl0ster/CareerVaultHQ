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
            return "\n".join(f"- {li.get_text(' ', strip=True)}" for li in el.find_all("li") if li.get_text(strip=True))
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


def decode_rsc(html: str) -> str:
    """Return the React Server Components payload embedded in a Next.js page.
    The page pushes JSON-escaped string chunks via ``self.__next_f.push([1, "..."])``."""
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', html, re.S)
    parts = []
    for chunk in chunks:
        try:
            parts.append(json.loads('"' + chunk + '"'))
        except json.JSONDecodeError:
            parts.append(chunk)
    return "\n".join(parts)


def rsc_object(payload: str, prefix: str) -> dict:
    """The first JSON object in a decoded RSC payload that starts with ``prefix``
    (e.g. ``'{"offers":['``); ``{}`` when absent or malformed."""
    start = payload.find(prefix)
    if start < 0:
        return {}
    try:
        data, _ = json.JSONDecoder().raw_decode(payload, start)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def resolve_rsc_ref(payload: str, value):
    """Resolve a ``"$NN"`` reference in an RSC payload to its text row. Long strings
    are stored as rows of the form ``NN:T<hex len>,<text>``."""
    if not isinstance(value, str) or not value.startswith("$"):
        return value
    row_id = value[1:]
    match = re.search(r"(?:^|\n)" + re.escape(row_id) + r":T([0-9a-f]+),", payload)
    if not match:
        return ""
    length = int(match.group(1), 16)
    return payload[match.end() :].encode("utf-8")[:length].decode("utf-8", errors="ignore")


def parse_pracuj_sections(sections: list | None) -> str:
    """Render the section model shared by Pracuj Group sites (theprotocol.it, pracuj.pl):
    titled sections with bullets / paragraphs / dictionaries and optional nested
    ``subSections``."""

    def render(section: dict) -> str:
        title = (section.get("title") or "").strip()
        parts: list[str] = []
        model = section.get("model") or {}
        kind = model.get("modelType")
        if kind == "multi-paragraph":
            parts.extend(p for p in model.get("paragraphs") or [] if p)
        elif kind == "bullets":
            parts.extend(f"- {b}" for b in model.get("bullets") or [] if b)
        elif kind == "open-dictionary":
            items = (model.get("items") or []) + (model.get("customItems") or [])
            names = [i.get("name") for i in items if isinstance(i, dict) and i.get("name")]
            if names:
                parts.append(", ".join(names))
        elif kind == "flag":
            parts.append("yes" if model.get("flag") else "no")
        elif kind and model.get("text"):
            parts.append(str(model["text"]))
        for sub in section.get("subSections") or []:
            sub_title = (sub.get("title") or "").strip()
            sub_text = render(sub)
            if sub_text:
                prefixed = sub_title and not sub_text.startswith(sub_title)
                parts.append(f"{sub_title}: {sub_text}" if prefixed else sub_text)
        content = "\n".join(parts)
        if title and content and not content.startswith(title):
            return f"{title}:\n{content}"
        return content

    return "\n\n".join(filter(None, (render(s) for s in sections or [])))
