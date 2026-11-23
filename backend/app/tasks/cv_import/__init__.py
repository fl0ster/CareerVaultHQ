"""CV import: parse an uploaded CV PDF into personal details and work history.

``import_cv`` is the RQ job enqueued by ``POST /api/cv-import``; its return value (a
``CvImportResult`` dump) is served by ``GET /api/cv-import/jobs/{job_id}``. Nothing is
written to the candidate's data: the client reviews the result and saves it through
``PUT /api/candidate-details`` and ``POST /api/work-history/json``.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.db import init_db, session_factory
from app.services.openrouter import OpenRouterService
from app.tasks.cv_import.extract import CvImportError, CvImportResult, extract_cv, extract_pdf

log = logging.getLogger(__name__)

__all__ = ["CvImportError", "CvImportResult", "import_cv"]


def _remove_upload(path: Path) -> None:
    """Delete the uploaded PDF (personal data) and its per-upload directory."""
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)
        path.parent.rmdir()


def import_cv(path: str) -> dict[str, Any]:
    """Parse the CV PDF at ``path`` and return the ``CvImportResult`` as JSON-ready data.
    The file is deleted afterwards, whatever the outcome. Raises ``CvImportError`` (shown
    to the user) or ``OpenRouterError`` so RQ marks the job failed."""
    settings = get_settings()
    pdf_path = Path(path)
    try:
        pdf = extract_pdf(
            pdf_path,
            max_pages=settings.cv_import_max_pages,
            max_chars=settings.cv_import_max_chars,
            min_chars=settings.cv_import_min_text_chars,
        )
        init_db()
        with session_factory()() as session:
            result = extract_cv(OpenRouterService(session, settings), pdf, settings)
    finally:
        _remove_upload(pdf_path)
    log.info("Imported CV: %d positions, %d warnings", len(result.work_history), len(result.warnings))
    return result.model_dump(mode="json")
