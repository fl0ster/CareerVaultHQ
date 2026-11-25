import shutil

import pytest

from app.tasks.cv.render import (
    PLACEHOLDERS,
    collect_technologies,
    fill_template,
    load_template,
    render_consent,
    render_contacts,
    render_cv,
    render_early_history,
    render_education,
    render_headline,
    render_role,
    render_roles,
    split_sentences,
    tex_escape,
)
from app.tasks.latex import compile_latex

DETAILS = {
    "first_name": "Jane",
    "last_name": "Doe & Co",
    "email": "jane@example.com",
    "phone": "+48 600 000 000",
    "website": "https://www.janedoe.dev/",
    "github": "github.com/jane_doe",
    "linkedin": "",
    "location": "Kraków",
    "education": [
        {
            "degree": "B.Sc. Computer Science",
            "institution": "Some University",
            "date_start": "Oct 2012",
            "date_end": "May 2015",
            "note": "",
        }
    ],
    "certifications": ["AWS Cloud Technical Essentials", " "],
    "languages": [{"language": "Polish", "level": "Native"}, {"language": "", "level": "x"}],
    "consent_text": "I consent to 100% of the processing.\n\nDrugi akapit.",
}

MAIN = [
    {
        "date_start": "Jul 2024",
        "date_end": "Present",
        "employer": "VGW",
        "role": "Senior Mobile Engineer",
        "location": "Remote",
        "tech": "React Native, TypeScript",
        "context": "Built CI/CD pipelines. Reduced ANR rate from 4% to 0.45%.",
    }
]
EARLY = [
    {
        "date_start": "Jan 2015",
        "date_end": "Dec 2016",
        "employer": "Old_Corp",
        "role": "Junior Dev",
        "location": None,
        "tech": "PHP",
        "context": "Maintained a legacy shop.",
    }
]


PROMOTED = [
    {
        "date_start": "Mar 2022",
        "date_end": "Jun 2024",
        "employer": "Acme",
        "role": "Lead Engineer",
        "location": "Warsaw",
        "tech": "Kotlin",
        "context": "Led a team of five.",
        "transition": "promotion",
        "tenure": 7,
    },
    {
        "date_start": "Jan 2019",
        "date_end": "Feb 2022",
        "employer": "Acme",
        "role": "Engineer",
        "location": "Warsaw",
        "tech": "Java",
        "context": "Built the checkout.",
        "tenure": 7,
    },
]


def test_tex_escape():
    assert tex_escape("A & B 100% #1 $x$ a_b {c} ~ ^ \\") == (
        r"A \& B 100\% \#1 \$x\$ a\_b \{c\} \textasciitilde{} \textasciicircum{} "
        r"\textbackslash{}"
    )
    assert tex_escape(None) == ""


def test_split_sentences():
    assert split_sentences("One. Two! Three? four. 5th sentence.") == [
        "One.",
        "Two!",
        "Three? four.",
        "5th sentence.",
    ]
    assert split_sentences(None) == []


def test_render_role_and_early_history():
    tex = render_role(MAIN[0])
    assert tex.startswith("\\begin{cvrole}{Senior Mobile Engineer}{VGW}{Jul 2024 -- Present}{Remote}")
    assert "\\item Built CI/CD pipelines." in tex
    assert "\\item Reduced ANR rate from 4\\% to 0.45\\%." in tex
    assert "\\cvtech{React Native, TypeScript}" in tex

    early = render_early_history(EARLY)
    assert "{Additional Experience}{Various Companies}{Jan 2015 -- Dec 2016}" in early
    assert "\\textbf{Junior Dev}" in early and "Old\\_Corp" in early
    assert "Maintained a legacy shop}" in early  # trailing period stripped
    assert render_early_history([]) == ""


def test_render_role_with_list_context_and_no_tech():
    tex = render_role({**MAIN[0], "context": ["a", "b"], "tech": []})
    assert "\\item a\n  \\item b" in tex
    assert "\\cvtech" not in tex


def test_collect_technologies_dedupes_case_insensitively():
    entries = [{"tech": "React, TypeScript, react"}, {"tech": ["Jest", " typescript "]}]
    assert collect_technologies(entries) == ["React", "TypeScript", "Jest"]


def test_render_contacts_and_headline():
    contacts = render_contacts(DETAILS)
    assert "\\href{mailto:jane@example.com}{jane@example.com}" in contacts
    assert "\\href{https://www.janedoe.dev/}{janedoe.dev}" in contacts
    assert "\\href{https://github.com/jane\\_doe}{github.com/jane\\_doe}" in contacts
    assert "linkedin" not in contacts
    assert contacts.endswith("Kraków")
    assert render_contacts({}) == ""

    assert render_headline("Senior Engineer", ["React Native", "TypeScript"]) == (
        "Senior Engineer\\ \\textperiodcentered\\ \\ React Native\\ \\textperiodcentered\\ \\ TypeScript"
    )
    assert render_headline("", []) == ""


def test_render_education_variants():
    both = render_education(DETAILS["education"], DETAILS["certifications"])
    assert both.startswith("\\begin{cvsectionblock}{Education \\& Certifications}")
    assert "\\textbf{B.Sc. Computer Science} \\hfill" in both
    assert "Oct 2012 -- May 2015" in both
    assert "\\item AWS Cloud Technical Essentials" in both
    assert render_education(DETAILS["education"], []).startswith("\\begin{cvsectionblock}{Education}")
    assert render_education([], ["X"]).startswith("\\begin{cvsectionblock}{Certifications}")
    assert render_education([], []) == ""
    assert render_education([{"degree": "", "institution": ""}], []) == ""


def test_render_consent_keeps_paragraphs():
    tex = render_consent(DETAILS["consent_text"])
    assert "100\\% of the processing.\\par\\vspace{4pt}Drugi akapit." in tex
    assert render_consent("  \n ") == ""


def test_fill_template_requires_every_placeholder():
    values = {p: "" for p in PLACEHOLDERS}
    assert fill_template(" ".join(PLACEHOLDERS), values) == " " * (len(PLACEHOLDERS) - 1)
    values["__NAME__"] = "x"
    filled = fill_template(" ".join(PLACEHOLDERS) + " __NAME__", values)
    assert filled.count("x") == 2 and "__" not in filled
    with pytest.raises(ValueError, match="does not contain"):
        fill_template("__NAME__", values)
    with pytest.raises(ValueError, match="no value"):
        fill_template(" ".join(PLACEHOLDERS), {})


def _render():
    return render_cv(
        template=load_template(),
        details=DETAILS,
        headline_role="Senior React Native Engineer",
        core_technologies=["React Native", "TypeScript"],
        summary="Senior mobile engineer with 10+ years & measurable impact.",
        main=MAIN + PROMOTED,
        early=EARLY,
        categories=[("Mobile", ["React Native"]), ("Languages", ["TypeScript"])],
    )


def test_render_cv_fills_everything():
    tex = _render()
    assert all(p not in tex for p in PLACEHOLDERS)
    # Placeholders are only ever replaced inside the document, never in comments.
    assert "Built CI/CD pipelines" not in tex.split("\\begin{document}")[0]
    assert "\\bfseries Jane Doe \\& Co\\par" in tex
    assert "pdfauthor={Jane Doe \\& Co}" in tex
    assert "pdfsubject={Senior React Native Engineer}" in tex
    assert "10+ years \\& measurable impact." in tex
    assert "\\cvitem{Mobile}{{\\color{muted}React Native}}" in tex
    assert "\\cvitem{Polish}{{\\color{muted}Native}}" in tex
    assert "Drugi akapit." in tex


def test_render_cv_omits_empty_sections():
    tex = render_cv(
        template=load_template(),
        details={"first_name": "A", "last_name": "B"},
        headline_role="",
        core_technologies=[],
        summary="",
        main=MAIN,
        early=[],
        categories=[],
    )
    body = tex.split("\\begin{document}")[1]
    assert "cvsectionblock" not in body
    assert "cvblock}" not in body


pdflatex_missing = shutil.which("pdflatex") is None


@pytest.mark.skipif(pdflatex_missing, reason="pdflatex not installed")
def test_rendered_cv_compiles(tmp_path):
    tex = tmp_path / "cv.tex"
    tex.write_text(_render(), encoding="utf-8")
    result = compile_latex(str(tex), passes=1, timeout=180)
    assert (tmp_path / "cv.pdf").read_bytes().startswith(b"%PDF")
    assert "Output written" in result["log_tail"]


def test_roles_of_one_tenure_share_an_employer_block():
    tex = render_roles(MAIN + PROMOTED, [])
    assert tex.count("\\begin{cvrole}") == 2
    assert "\\begin{cvrole}{Lead Engineer}{Acme}{Mar 2022 -- Jun 2024}{Warsaw}" in tex
    assert "\\begin{cvsubrole}{Engineer}{Jan 2019 -- Feb 2022}\n  \\item Built the checkout.\n  \\cvtech{Java}" in tex
    # the sub-role follows its employer block directly
    assert tex.index("\\end{cvrole}\n\\begin{cvsubrole}") > tex.index("Lead Engineer")


def test_early_roles_of_one_tenure_share_a_line():
    early = [{**e, "context": "Did things."} for e in PROMOTED] + EARLY
    tex = render_early_history(early)
    assert "\\textbf{Engineer $\\rightarrow$ Lead Engineer}, {\\small {\\color{muted}Acme (Jan 2019 -- Jun 2024)}" in tex
    assert "Did things; Did things}" in tex
    assert tex.count("\\item") == 2
