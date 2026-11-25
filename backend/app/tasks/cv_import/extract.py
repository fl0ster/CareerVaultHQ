"""CV PDF -> structured personal details and work history (a preview; nothing is saved).

Pipeline:

1. ``extract_pdf``: the text layer (``pypdf``, plain content-stream order) plus the URIs of
   the link annotations, which often carry the LinkedIn / GitHub address behind a label.
   A PDF without a usable text layer (a scan) is rejected; there is no OCR.
2. ``extract_cv``: one chat completion at ``temperature=0`` asking for a strict JSON schema
   (``prompts.RESPONSE_FORMAT``), sent with ``private=True`` so the CV is not stored in
   ``openrouter_calls``.
3. Lenient post-processing: every section is validated on its own, dropping (with a
   warning) what does not fit instead of failing the import. Contact details must occur in
   the CV (anti-hallucination) and missing ones are backfilled from the text and links.
   Positions, education and certificates become one career timeline (``kind`` = ``job``,
   ``education``, ``certificate``) with dates normalised to the ``Jan 2020`` format of the
   JSON import.

The result uses the request shapes of ``PUT /api/candidate-details``
(``CandidateDetailsIn``) and ``POST /api/work-history/json`` (``WorkHistoryImport``).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from pypdf import PageObject, PdfReader

from app import llm_calls
from app.config import Settings
from app.models import WorkHistoryEntry
from app.schemas.candidate_details import CandidateDetailsIn, LanguageEntry
from app.schemas.work_history import MONTH_FORMAT, WorkHistoryImport, _clean_tech
from app.services.openrouter import OpenRouterService
from app.tasks.cv_import.prompts import CV_IMPORT_PROMPT, CV_IMPORT_SYSTEM, RESPONSE_FORMAT

log = logging.getLogger(__name__)


CURRENT_MARKERS = {"present", "current", "now", "today", "ongoing", "obecnie", "teraz", "nadal"}
"""``date_end`` values meaning the position is current."""

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_LINKEDIN = re.compile(r"linkedin\.com/in/[\w%-]+", re.IGNORECASE)
_GITHUB = re.compile(r"github\.com/(?!orgs/|topics/|features/)[A-Za-z0-9-]+", re.IGNORECASE)
_YEAR_MONTH = re.compile(r"^(\d{4})[-/.](\d{1,2})$")
_MONTH_YEAR = re.compile(r"^(\d{1,2})[-/.](\d{4})$")
_YEAR = re.compile(r"^\d{4}$")


class CvImportError(Exception):
    """The CV cannot be imported; the message is meant for the user."""


# --------------------------------------------------------------------------- result


class CvImportSource(BaseModel):
    pages: int
    """Pages in the PDF."""
    pages_read: int
    """Pages whose text was used (at most ``cv_import_max_pages``)."""
    characters: int
    """Characters of text sent to the LLM."""
    links: list[str] = Field(default_factory=list)
    """Hyperlinks found in the PDF."""


class CvImportResult(BaseModel):
    candidate_details: CandidateDetailsIn
    """Ready for ``PUT /api/candidate-details`` (``photo`` and ``consent_text`` are blank)."""
    work_history: list[WorkHistoryImport]
    """Positions, education and certificates, ready for ``POST /api/work-history/json``;
    newest first."""
    skills: list[str]
    """Skills listed outside any position (no field stores them yet)."""
    summary: str | None
    """The CV's profile / summary paragraph."""
    warnings: list[str]
    """What was dropped, guessed or truncated; worth showing the user before saving."""
    source: CvImportSource


# --------------------------------------------------------------------------- PDF


@dataclass
class PdfText:
    text: str
    links: list[str]
    pages: int
    pages_read: int
    warnings: list[str] = field(default_factory=list)


def _page_links(page: PageObject) -> list[str]:
    """URIs of the page's link annotations (``/Annots`` -> ``/A`` -> ``/URI``)."""
    if "/Annots" not in page:
        return []
    links: list[str] = []
    for ref in page["/Annots"]:
        annot = ref.get_object()
        if annot.get("/Subtype") != "/Link" or "/A" not in annot:
            continue
        uri = annot["/A"].get_object().get("/URI")
        if uri:
            links.append(str(uri).strip())
    return links


def _tidy(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def extract_pdf(path: Path, *, max_pages: int, max_chars: int, min_chars: int) -> PdfText:
    """Text and hyperlinks of the first ``max_pages`` pages, truncated to ``max_chars``.
    Raises ``CvImportError`` for unreadable or password-protected PDFs and for PDFs with
    fewer than ``min_chars`` non-whitespace characters of text (scans)."""
    try:
        reader = PdfReader(path)
        if reader.is_encrypted and not reader.decrypt(""):
            raise CvImportError("the PDF is password-protected; upload an unprotected copy")
        total = len(reader.pages)
        read = min(total, max_pages)
        texts: list[str] = []
        links: list[str] = []
        for index in range(read):
            page = reader.pages[index]
            texts.append(page.extract_text() or "")
            try:
                links.extend(_page_links(page))
            except Exception:  # a malformed annotation must not lose the text
                log.warning("Could not read the link annotations of page %d", index + 1, exc_info=True)
    except CvImportError:
        raise
    except Exception as exc:
        raise CvImportError(f"could not read the PDF: {exc}") from exc

    text = _tidy("\n\n".join(texts))
    if len(re.sub(r"\s", "", text)) < min_chars:
        raise CvImportError("the PDF has no text layer (is it a scan?); upload a text-based PDF")

    warnings: list[str] = []
    if total > read:
        warnings.append(f"only the first {read} of {total} pages were read")
    if len(text) > max_chars:
        text = text[:max_chars]
        warnings.append(f"the CV text was cut to its first {max_chars} characters")
    return PdfText(text=text, links=list(dict.fromkeys(links)), pages=total, pages_read=read, warnings=warnings)


# --------------------------------------------------------------------------- LLM reply


def _load_reply(reply: str) -> dict[str, Any]:
    """The JSON object in the reply: plain, fenced, or surrounded by prose."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", reply.strip())
    candidates = [text]
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    raise CvImportError("the model did not answer with a JSON object; try again")


def _str(value: Any, max_length: int | None = None, *, multiline: bool = False) -> str:
    """A trimmed string (whitespace collapsed unless ``multiline``); non-strings -> ``""``."""
    if not isinstance(value, str):
        return ""
    if multiline:
        text = _tidy(value)
    else:
        text = " ".join(value.split())
    return text[:max_length] if max_length else text


def _strs(value: Any, max_length: int | None = None) -> list[str]:
    if not isinstance(value, list):
        return []
    return [s for s in (_str(item, max_length) for item in value) if s]


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


# --------------------------------------------------------------------------- dates


def _month(value: str) -> tuple[date | None, bool]:
    """``(first day of the month, year_only)`` for ``YYYY-MM``, ``MM/YYYY``, ``YYYY`` or the
    import formats (``Jan 2020``, ``January 2020``); ``(None, False)`` when unparseable."""
    if match := _YEAR_MONTH.match(value):
        year, month = int(match[1]), int(match[2])
    elif match := _MONTH_YEAR.match(value):
        month, year = int(match[1]), int(match[2])
    elif _YEAR.match(value):
        return date(int(value), 1, 1), True
    else:
        for fmt in (MONTH_FORMAT, "%B %Y"):
            try:
                return datetime.strptime(value, fmt).date(), False
            except ValueError:
                continue
        return None, False
    if not 1 <= month <= 12:
        return None, False
    return date(year, month, 1), False


# --------------------------------------------------------------------------- grounding


def _squash(text: str) -> str:
    return re.sub(r"\s", "", text).lower()


def _url_key(url: str) -> str:
    """``https://www.LinkedIn.com/in/x/`` -> ``linkedin.com/in/x`` (the form the forms use)."""
    text = url.strip()
    text = re.sub(r"^[a-z][a-z0-9+.-]*://", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^www\.", "", text, flags=re.IGNORECASE)
    return text.split("?")[0].split("#")[0].rstrip("/")


class _Source:
    """The CV text plus its hyperlinks, for checking that extracted values were stated."""

    def __init__(self, pdf: PdfText) -> None:
        self.links = pdf.links
        self.squashed = _squash(pdf.text + "\n" + "\n".join(pdf.links))
        self.digits = re.sub(r"\D", "", pdf.text + " ".join(pdf.links))

    def has(self, value: str) -> bool:
        return _squash(value) in self.squashed

    def has_url(self, value: str) -> bool:
        return self.has(_url_key(value).lower())

    def has_phone(self, value: str) -> bool:
        digits = re.sub(r"\D", "", value)
        return len(digits) >= 6 and digits in self.digits

    def first(self, pattern: re.Pattern[str], text: str) -> str:
        for candidate in [*self.links, text]:
            if match := pattern.search(candidate):
                return match.group(0)
        return ""


def _contacts(data: dict[str, Any], pdf: PdfText, warnings: list[str]) -> dict[str, str]:
    """Name, contact lines and location: grounded in the CV, backfilled when missing."""
    source = _Source(pdf)
    contacts = {
        "first_name": _str(data.get("first_name"), 128),
        "last_name": _str(data.get("last_name"), 128),
        "location": _str(data.get("location"), 256),
        "email": _str(data.get("email"), 256),
        "phone": _str(data.get("phone"), 64),
        "website": _str(data.get("website"), 512),
        "github": _str(data.get("github"), 512),
        "linkedin": _str(data.get("linkedin"), 512),
    }

    checks = {"email": source.has, "phone": source.has_phone}
    for key in ("website", "github", "linkedin"):
        checks[key] = source.has_url
    for key, check in checks.items():
        if contacts[key] and not check(contacts[key]):
            warnings.append(f"{key} {contacts[key]!r} was not found in the CV and was dropped")
            contacts[key] = ""

    if not contacts["email"]:
        mailto = next((link[7:] for link in source.links if link.lower().startswith("mailto:")), "")
        contacts["email"] = (_EMAIL.search(mailto) or _EMAIL.search(pdf.text) or [""])[0][:256]
    if not contacts["phone"]:
        tel = next((link[4:] for link in source.links if link.lower().startswith("tel:")), "")
        contacts["phone"] = tel.strip()[:64]
    if not contacts["linkedin"]:
        contacts["linkedin"] = source.first(_LINKEDIN, pdf.text)
    if not contacts["github"]:
        contacts["github"] = source.first(_GITHUB, pdf.text)
    for key in ("website", "github", "linkedin"):
        contacts[key] = _url_key(contacts[key])[:512]

    if not (contacts["first_name"] or contacts["last_name"]):
        warnings.append("the candidate's name was not found")
    return contacts


# --------------------------------------------------------------------------- sections


Dated = tuple[date, WorkHistoryImport]
"""A timeline entry with its start date, for sorting."""


def _dates(item: dict[str, Any], kind: str, label: str, warnings: list[str]) -> tuple[date, date | None] | None:
    """``(start, end)`` of a timeline entry, or ``None`` (with a warning) when no start date
    can be read. A missing end means a current position / ongoing education, and a
    certificate without a duration; an education or certificate stating only its end
    (graduation, issue date) starts there."""
    start_text = _str(item.get("date_start"))
    end_text = _str(item.get("date_end"))
    start, start_year_only = _month(start_text)
    end: date | None = None
    end_year_only = False
    if end_text.lower() in CURRENT_MARKERS:
        pass
    elif end_text:
        end, end_year_only = _month(end_text)
        if end is None:
            ongoing = "a single date" if kind == "certificate" else "ongoing"
            warnings.append(f"{label}: the end date {end_text!r} could not be read, so it is treated as {ongoing}")
    elif kind == "job":
        warnings.append(f"{label}: no end date is stated, so it is treated as a current position")

    if start is None and kind != "job" and end is not None:
        start, start_year_only = end, end_year_only
        if kind == "education":
            warnings.append(f"{label}: only the end date is stated, so it is shown as a single month")
        else:
            end = None
    if start is None:
        if kind == "job":
            warnings.append(f"skipped {label}: no start date could be read ({start_text!r})")
        else:
            warnings.append(f"skipped {label}: no date could be read, add it by hand")
        return None
    if kind == "education" and end is None and not end_text:
        warnings.append(f"{label}: no end date is stated, so it is treated as ongoing")
    if start_year_only or end_year_only:
        warnings.append(f"{label}: only the year is stated, so January was assumed")
    if end is not None and end < start:
        warnings.append(f"{label}: the end date was before the start date, so they were swapped")
        start, end = end, start
    return start, end


def _entry(
    kind: str, item: dict[str, Any], title: str, organisation: str, label: str, warnings: list[str], **fields: Any
) -> Dated | None:
    dates = _dates(item, kind, label, warnings)
    if dates is None:
        return None
    start, end = dates
    entry = WorkHistoryImport(
        kind=kind,
        date_start=start.strftime(MONTH_FORMAT),
        date_end=end.strftime(MONTH_FORMAT) if end else None,
        employer=organisation,
        role=title,
        **fields,
    )
    try:
        entry.to_create()  # exactly what POST /work-history/json will run
    except (ValueError, ValidationError) as exc:
        warnings.append(f"skipped {label}: {exc}")
        return None
    return start, entry


def _work_entry(item: dict[str, Any], warnings: list[str]) -> Dated | None:
    employer = _str(item.get("employer"), 256)
    role = _str(item.get("role"), 256)
    label = " at ".join(part for part in (role, employer) if part) or "an untitled position"
    if not employer or not role:
        warnings.append(f"skipped {label}: the employer or the role is missing")
        return None
    return _entry(
        "job",
        item,
        role,
        employer,
        label,
        warnings,
        location=_str(item.get("location"), 256) or None,
        tech=_clean_tech(_strs(item.get("tech"))),
        context=_str(item.get("context"), multiline=True) or None,
        transition=_transition(item.get("transition")),
    )


def _transition(value: Any) -> str | None:
    """A promotion / role change within the employer of the previous position; anything
    else (blank or unknown) means a new employment."""
    text = _str(value).lower()
    return text if text in WorkHistoryEntry.TRANSITIONS else None


def _education_entry(item: dict[str, Any], warnings: list[str]) -> Dated | None:
    degree = _str(item.get("degree"), 256)
    institution = _str(item.get("institution"), 256)
    if not (degree or institution):
        return None
    label = " at ".join(part for part in (degree, institution) if part)
    # the title is required; a CV naming only the school still gets an entry
    title, organisation = (degree, institution) if degree else (institution, "")
    note = _str(item.get("note"), multiline=True) or None
    return _entry("education", item, title, organisation, f"education {label}", warnings, context=note)


_YEAR_IN_TEXT = re.compile(r"\b(19|20)\d{2}\b")


def _certificate_entry(item: dict[str, Any] | str, warnings: list[str]) -> Dated | None:
    if isinstance(item, str):
        # models without structured output may still answer with plain strings
        year = _YEAR_IN_TEXT.search(item)
        item = {"name": item, "issuer": "", "date_start": year.group(0) if year else "", "date_end": ""}
    name = _str(item.get("name"), 256)
    if not name:
        return None
    issuer = _str(item.get("issuer"), 256)
    label = f"certificate {name}" + (f" ({issuer})" if issuer else "")
    return _entry("certificate", item, name, issuer, label, warnings)


def _timeline(data: dict[str, Any], warnings: list[str]) -> list[WorkHistoryImport]:
    """Positions, education and certificates as one timeline, newest first."""
    jobs = [entry for item in _dicts(data.get("work_history")) if (entry := _work_entry(item, warnings))]
    if not jobs:
        warnings.append("no work history was found")
    education = [entry for item in _dicts(data.get("education")) if (entry := _education_entry(item, warnings))]
    raw_certificates = data.get("certifications")
    certificates = [
        entry
        for item in (raw_certificates if isinstance(raw_certificates, list) else [])
        if isinstance(item, dict | str) and (entry := _certificate_entry(item, warnings))
    ]
    entries = _dedupe([*jobs, *education, *certificates])
    entries.sort(key=lambda pair: pair[0], reverse=True)
    return [entry for _, entry in entries]


def _dedupe(entries: list[Dated]) -> list[Dated]:
    """Drop repeated entries (same kind, title, organisation and start)."""
    seen: set[tuple[str, str, str, str]] = set()
    out: list[Dated] = []
    for start, entry in entries:
        key = (entry.kind, entry.role.lower(), entry.employer.lower(), entry.date_start)
        if key not in seen:
            seen.add(key)
            out.append((start, entry))
    return out


def _languages(data: dict[str, Any]) -> list[LanguageEntry]:
    entries = [
        LanguageEntry(language=_str(item.get("language"), 64), level=_str(item.get("level"), 128))
        for item in _dicts(data.get("languages"))
    ]
    return [entry for entry in entries if entry.language]


def build_result(data: dict[str, Any], pdf: PdfText) -> CvImportResult:
    """Validated result from the model's JSON ``data`` (see the module docstring)."""
    warnings = list(pdf.warnings)
    details = CandidateDetailsIn(**_contacts(data, pdf, warnings), languages=_languages(data))
    return CvImportResult(
        candidate_details=details,
        work_history=_timeline(data, warnings),
        skills=_clean_tech(_strs(data.get("skills"))),
        summary=_str(data.get("summary"), multiline=True) or None,
        warnings=warnings,
        source=CvImportSource(pages=pdf.pages, pages_read=pdf.pages_read, characters=len(pdf.text), links=pdf.links),
    )


def extract_cv(service: OpenRouterService, pdf: PdfText, settings: Settings) -> CvImportResult:
    """Ask the model for the CV's data and validate it. Raises ``CvImportError`` when the
    reply is not JSON; OpenRouter errors propagate."""
    links = "\n".join(f"- {link}" for link in pdf.links) or "(none)"
    reply = service.chat(
        CV_IMPORT_PROMPT.format(text=pdf.text, links=links),
        system=CV_IMPORT_SYSTEM,
        temperature=0,
        extra={"response_format": RESPONSE_FORMAT},
        call=llm_calls.CV_IMPORT,
        private=True,
    ).text
    return build_result(_load_reply(reply), pdf)
