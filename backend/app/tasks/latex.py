"""Compile a finished ``.tex`` document into a PDF.

This is the last step of the original CV pipeline (``_ref/building_cv/run_pipeline.py``):
run ``pdflatex`` a couple of times with ``-interaction=nonstopmode -halt-on-error`` so
cross-references settle, writing all artefacts next to the source file.

The function runs inside the RQ worker process, never in the web server.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.config import get_settings

LOG_TAIL_CHARS = 4000


class LatexCompileError(RuntimeError):
    """Raised when the compiler is missing, times out or exits non-zero."""

def _log_tail(log_file: Path) -> str:
    if not log_file.is_file():
        return ""
    text = log_file.read_text(encoding="utf-8", errors="replace")
    return text[-LOG_TAIL_CHARS:]


def compile_latex(
    tex_path: str,
    *,
    out_dir: str | None = None,  # defaults to the source's directory
    passes: int | None = None,
    timeout: int | None = None,
    compiler: str | None = None,
) -> dict[str, Any]:
    """Compile ``tex_path`` and return where the PDF landed.

    Returns ``{"pdf": <abs path>, "log": <abs path>, "log_tail": str, "passes": int}``.
    Raises :class:`LatexCompileError` (with the log tail in the message) on failure so
    RQ marks the job as failed and the API can surface the reason.
    """
    settings = get_settings()
    passes = passes or settings.latex_passes
    timeout = timeout or settings.latex_timeout
    compiler = compiler or settings.latex_compiler

    source = Path(tex_path).resolve()
    if not source.is_file():
        raise LatexCompileError(f"source file not found: {source}")

    binary = shutil.which(compiler)
    if binary is None:
        raise LatexCompileError(f"{compiler!r} not found on PATH")

    out_path = Path(out_dir).resolve() if out_dir else source.parent
    out_path.mkdir(parents=True, exist_ok=True)
    jobname = source.stem
    log_file = out_path / f"{jobname}.log"
    pdf_file = out_path / f"{jobname}.pdf"

    cmd = [
        binary,
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-no-shell-escape",  # uploaded documents are untrusted
        f"-output-directory={out_path}",
        f"-jobname={jobname}",
        source.name,
    ]
    # Keep TeX from reading/writing outside the job folder (TeX Live "paranoid" mode).
    env = {**os.environ, "openin_any": "p", "openout_any": "p", "TEXMFOUTPUT": str(out_path)}

    for i in range(1, passes + 1):
        try:
            result = subprocess.run(
                cmd,
                cwd=source.parent,  # the .tex lives here; artefacts go to out_path
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise LatexCompileError(
                f"{compiler} pass {i}/{passes} timed out after {timeout}s\n{_log_tail(log_file)}"
            ) from exc

        if result.returncode != 0:
            stdout = result.stdout.decode("utf-8", errors="replace")
            tail = _log_tail(log_file) or stdout[-LOG_TAIL_CHARS:]
            raise LatexCompileError(
                f"{compiler} pass {i}/{passes} exited with code {result.returncode}\n{tail}"
            )

    if not pdf_file.is_file():
        raise LatexCompileError(f"{compiler} finished but {pdf_file.name} was not produced")

    return {
        "pdf": str(pdf_file),
        "log": str(log_file),
        "log_tail": _log_tail(log_file),
        "passes": passes,
    }
