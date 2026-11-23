"""Prompt and JSON schema for extracting a CV's text into structured data."""

from __future__ import annotations

from typing import Any

CV_IMPORT_SYSTEM = (
    "You extract structured data from CVs (résumés). Answer with a single JSON object that "
    "matches the requested schema and nothing else."
)

CV_IMPORT_PROMPT = """Below is the text of a CV extracted from a PDF (the reading order may be
slightly off for multi-column layouts), followed by the hyperlinks embedded in the PDF.
Extract the candidate's data into the JSON object described by the schema.

Rules:
- Only use information stated in the CV. Never guess or invent; use "" (or an empty list)
  for anything that is not stated.
- Keep the CV's language for free text (roles, descriptions, degrees, language levels).
- Contact details: copy e-mail, phone and URLs exactly as written. "website" is a personal
  site or portfolio (not GitHub or LinkedIn). Use the embedded hyperlinks when the text only
  shows a label such as "LinkedIn" or "GitHub".
- "location" is the candidate's city/country, not an employer's.
- work_history: one entry per position (a promotion at the same employer is a separate
  entry). Include internships and freelance work; exclude education and volunteering
  unless presented as work experience.
  - "employer": the company or client name; "role": the job title.
  - "date_start" / "date_end": "YYYY-MM" when the month is stated, "YYYY" when only the
    year is; "date_end" is "present" for a current position and "" when not stated.
  - "tech": the technologies, languages, frameworks and tools named for that position,
    each as a short name (e.g. "Python", "PostgreSQL", "AWS Lambda").
  - "context": the position's description and achievements, as in the CV (keep bullet
    points as separate lines starting with "- ").
- education: one entry per degree or study programme: "degree" (with the field of study),
  "institution", dates in the same "YYYY-MM" / "YYYY" format ("date_end" is "present" while
  still studying and "" when not stated), and "note" for anything else stated (thesis,
  grade, specialisation).
- skills: skills listed outside any position (e.g. a "Skills" or "Technologies" section).
- certifications: one entry per certificate, licence or course: "name" (without the issuer
  or year), "issuer" (the organisation that issued it, "" when not stated), "date_start"
  (the issue date, or the start of a course that ran over a period) and "date_end" (only
  for a course or programme with a stated period; "" for a certificate issued on a single
  date), in the same "YYYY-MM" / "YYYY" format.
- languages: spoken languages with the level as written ("C1", "native", "fluent").
- summary: the CV's profile / about / summary paragraph, verbatim; "" when absent.

CV text:
<<<
{text}
>>>

Hyperlinks embedded in the PDF:
{links}"""

_STRING: dict[str, Any] = {"type": "string"}
_STRINGS: dict[str, Any] = {"type": "array", "items": _STRING}


def _object(**properties: dict[str, Any]) -> dict[str, Any]:
    """Strict-mode object: every property required, nothing else allowed."""
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


CV_IMPORT_SCHEMA: dict[str, Any] = _object(
    first_name=_STRING,
    last_name=_STRING,
    email=_STRING,
    phone=_STRING,
    location=_STRING,
    website=_STRING,
    github=_STRING,
    linkedin=_STRING,
    summary=_STRING,
    work_history={
        "type": "array",
        "items": _object(
            employer=_STRING,
            role=_STRING,
            location=_STRING,
            date_start=_STRING,
            date_end=_STRING,
            tech=_STRINGS,
            context=_STRING,
        ),
    },
    education={
        "type": "array",
        "items": _object(degree=_STRING, institution=_STRING, date_start=_STRING, date_end=_STRING, note=_STRING),
    },
    skills=_STRINGS,
    certifications={
        "type": "array",
        "items": _object(name=_STRING, issuer=_STRING, date_start=_STRING, date_end=_STRING),
    },
    languages={"type": "array", "items": _object(language=_STRING, level=_STRING)},
)

RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {"name": "cv", "strict": True, "schema": CV_IMPORT_SCHEMA},
}
"""OpenRouter structured-output request; models without support ignore it and the prompt
plus lenient parsing still apply."""
