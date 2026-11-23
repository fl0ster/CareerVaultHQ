"""Builds small CV PDFs for the CV import tests (no binary fixtures in the repo)."""

from __future__ import annotations

import io

from pypdf import PdfWriter
from pypdf.annotations import Link
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

CV_LINES = [
    "Jane Doe",
    "Senior Backend Engineer | Warsaw, Poland",
    "jane.doe@example.com | +48 600 700 800 | LinkedIn | GitHub",
    "",
    "Experience",
    "Acme Corp - Senior Backend Engineer - 03/2021 - present",
    "- Built payment services in Python, FastAPI and PostgreSQL",
    "- Led the migration to AWS Lambda",
    "Globex - Software Developer - 2018 - 02/2021",
    "- Django REST APIs, Celery workers and Redis caching",
    "",
    "Education",
    "MSc Computer Science, Warsaw University of Technology, 2013 - 2018",
    "",
    "Skills: Python, Go, Kubernetes, Terraform",
    "Languages: Polish (native), English (C1)",
]
CV_LINKS = ["https://www.linkedin.com/in/jane-doe/", "https://github.com/janedoe", "mailto:jane.doe@example.com"]


def _escape(line: str) -> str:
    return line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(
    lines: list[str] | None = None,
    *,
    links: list[str] | None = None,
    pages: int = 1,
    password: str | None = None,
) -> bytes:
    """A PDF whose every page shows ``lines`` (Helvetica) and carries ``links`` as link
    annotations; ``lines=[]`` gives pages without text, like a scan."""
    lines = CV_LINES if lines is None else lines
    links = CV_LINKS if links is None else links
    writer = PdfWriter()
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    for number in range(pages):
        page = writer.add_blank_page(612, 792)
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        ops = ["BT", "/F1 10 Tf", "14 TL", "50 750 Td"] + [f"({_escape(line)}) Tj T*" for line in lines] + ["ET"]
        stream = DecodedStreamObject()
        stream.set_data("\n".join(ops).encode("latin-1"))
        page[NameObject("/Contents")] = writer._add_object(stream)
        for index, url in enumerate(links):
            writer.add_annotation(
                page_number=number,
                annotation=Link(rect=(50, 50 + index * 20, 150, 65 + index * 20), url=url),
            )
    if password is not None:
        writer.encrypt(password, algorithm="RC4-128")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()
