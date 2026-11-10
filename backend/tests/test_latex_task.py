import shutil

import pytest

from app.tasks.latex import LatexCompileError, compile_latex

pdflatex_missing = shutil.which("pdflatex") is None
needs_pdflatex = pytest.mark.skipif(pdflatex_missing, reason="pdflatex not installed")


@needs_pdflatex
def test_compile_produces_pdf(tmp_path):
    tex = tmp_path / "cv.tex"
    tex.write_text("\\documentclass{article}\\begin{document}Hello CV\\end{document}\n")

    result = compile_latex(str(tex), passes=2, timeout=120)

    assert result["passes"] == 2
    assert (tmp_path / "cv.pdf").read_bytes().startswith(b"%PDF")
    assert result["pdf"] == str(tmp_path / "cv.pdf")
    assert "Output written" in result["log_tail"]


@needs_pdflatex
def test_compile_failure_surfaces_log(tmp_path):
    tex = tmp_path / "broken.tex"
    tex.write_text("\\documentclass{article}\\begin{document}\\undefinedmacro\\end{document}\n")

    with pytest.raises(LatexCompileError) as excinfo:
        compile_latex(str(tex), passes=1, timeout=120)

    assert "Undefined control sequence" in str(excinfo.value)
    assert not (tmp_path / "broken.pdf").exists()


def test_missing_source(tmp_path):
    with pytest.raises(LatexCompileError, match="not found"):
        compile_latex(str(tmp_path / "nope.tex"))


def test_missing_compiler(tmp_path):
    tex = tmp_path / "cv.tex"
    tex.write_text("x")
    with pytest.raises(LatexCompileError, match="not found on PATH"):
        compile_latex(str(tex), compiler="definitely-not-a-latex-binary")
