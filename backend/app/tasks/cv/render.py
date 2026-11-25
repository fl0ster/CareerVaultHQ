"""Fill the CV LaTeX template (``cv_template.tex`` next to this module).

Everything printed on the CV goes through :func:`tex_escape`; the template itself holds
only layout. Placeholders (``__NAME__``, ``__ROLES__``, ...) are replaced with plain
``str.replace``; :func:`fill_template` fails loudly when the template lacks one rather
than producing a silently unchanged document.
"""

from __future__ import annotations

import re
from pathlib import Path

TEMPLATE_PATH = Path(__file__).with_name("cv_template.tex")

PLACEHOLDERS = (
    "__NAME__",
    "__HEADLINE__",
    "__PDF_SUBJECT__",
    "__CONTACTS__",
    "__SUMMARY__",
    "__ROLES__",
    "__EDUCATION__",
    "__TECHNOLOGIES__",
    "__LANGUAGES__",
    "__CONSENT__",
)

SEPARATOR = r"\ \textperiodcentered\ \ "
"""Between the contact items and between the headline role and its technologies."""

_LATEX_SPECIALS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
_SPECIALS_RE = re.compile("|".join(re.escape(c) for c in _LATEX_SPECIALS))


def tex_escape(text: object) -> str:
    """Escape characters that have special meaning in LaTeX."""
    return _SPECIALS_RE.sub(lambda m: _LATEX_SPECIALS[m.group(0)], str(text or "")).strip()


def split_sentences(text: str | None) -> list[str]:
    """Split a prose paragraph into sentences for bullet points."""
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", (text or "").strip())
    return [p.strip() for p in parts if p.strip()]


# --------------------------------------------------------------------------- header


def _href(url: str, label: str | None = None) -> str:
    target = url if re.match(r"^[a-z]+:", url) else f"https://{url}"
    shown = label or re.sub(r"^https?://(www\.)?", "", url).rstrip("/")
    return f"\\href{{{tex_escape(target)}}}{{{tex_escape(shown)}}}"


def render_contacts(details: dict) -> str:
    """One line of contact items: email, phone, website, GitHub, LinkedIn, location."""
    items: list[str] = []
    if details.get("email"):
        email = details["email"].strip()
        items.append(f"\\href{{mailto:{tex_escape(email)}}}{{{tex_escape(email)}}}")
    if details.get("phone"):
        items.append(tex_escape(details["phone"]))
    for key in ("website", "github", "linkedin"):
        if details.get(key):
            items.append(_href(details[key].strip()))
    if details.get("location"):
        items.append(tex_escape(details["location"]))
    return SEPARATOR.join(items)


def render_headline(role: str, core_technologies: list[str]) -> str:
    parts = [tex_escape(role)] if role else []
    if core_technologies:
        parts.append(SEPARATOR.join(tex_escape(t) for t in core_technologies))
    return SEPARATOR.join(parts)


# --------------------------------------------------------------------------- roles


def _dates(entry: dict) -> str:
    return f"{tex_escape(entry.get('date_start'))} -- {tex_escape(entry.get('date_end'))}"


def _role_body(entry: dict) -> list[str]:
    """The bullets and the tech line of a role. ``context`` may be prose (split into
    sentences) or a list."""
    context = entry.get("context")
    bullets = context if isinstance(context, list) else split_sentences(context)
    lines = [f"  \\item {tex_escape(bullet)}" for bullet in bullets]
    if not bullets:
        lines.append("  \\item[] ")  # itemize must not be empty
    tech = entry.get("tech")
    if isinstance(tech, list):
        tech = ", ".join(tech)
    if tech:
        lines.append(f"  \\cvtech{{{tex_escape(tech)}}}")
    return lines


def render_role(entry: dict) -> str:
    """One ``cvrole`` block: the role with its employer, dates and location."""
    title = tex_escape(entry.get("role"))
    company = tex_escape(entry.get("employer"))
    location = tex_escape(entry.get("location"))
    head = f"\\begin{{cvrole}}{{{title}}}{{{company}}}{{{_dates(entry)}}}{{{location}}}"
    return "\n".join([head, *_role_body(entry), "\\end{cvrole}"])


def render_subrole(entry: dict) -> str:
    """One ``cvsubrole`` block: an earlier role at the employer of the block above it."""
    head = f"\\begin{{cvsubrole}}{{{tex_escape(entry.get('role'))}}}{{{_dates(entry)}}}"
    return "\n".join([head, *_role_body(entry), "\\end{cvsubrole}"])


def group_tenures(entries: list[dict]) -> list[list[dict]]:
    """Consecutive entries (newest first) of the same ``tenure`` grouped together: one
    employer block each. An entry without a ``tenure`` is a group of its own."""
    groups: list[list[dict]] = []
    for entry in entries:
        tenure = entry.get("tenure")
        if groups and tenure is not None and groups[-1][-1].get("tenure") == tenure:
            groups[-1].append(entry)
        else:
            groups.append([entry])
    return groups


def _early_context(entry: dict) -> str:
    context = entry.get("context")
    if isinstance(context, list):
        context = " ".join(context)
    return tex_escape(context).rstrip(",.")


def render_early_history(entries: list[dict]) -> str:
    """All early roles as a single ``cvrole`` block, one line per role (newest first); the
    roles of one tenure share a line (``Engineer -> Senior Engineer``)."""
    if not entries:
        return ""
    dates = f"{tex_escape(entries[-1].get('date_start'))} -- {tex_escape(entries[0].get('date_end'))}"
    lines = [f"\\begin{{cvrole}}{{Additional Experience}}{{Various Companies}}{{{dates}}}{{}}"]
    for group in group_tenures(entries):
        newest, oldest = group[0], group[-1]
        role = " $\\rightarrow$ ".join(tex_escape(e.get("role")) for e in reversed(group))
        company = tex_escape(newest.get("employer"))
        start = tex_escape(oldest.get("date_start"))
        end = tex_escape(newest.get("date_end"))
        context = "; ".join(c for c in (_early_context(e) for e in group) if c)
        line = f"\\textbf{{{role}}}, {{\\small {{\\color{{muted}}{company} ({start} -- {end})}}"
        if context:
            line += f": {context}"
        lines.append(f"  \\item {line}}}")
    lines.append("\\end{cvrole}")
    return "\n".join(lines)


def render_roles(main: list[dict], early: list[dict]) -> str:
    """The roles listed in full, one employer block per tenure (its newest role with the
    employer, the earlier ones as sub-roles), then the early history."""
    blocks = [
        "\n".join([render_role(group[0]), *(render_subrole(entry) for entry in group[1:])]) for group in group_tenures(main)
    ]
    early_tex = render_early_history(early)
    if early_tex:
        blocks.append(early_tex)
    return "\n\n".join(blocks)


# --------------------------------------------------------------------------- skills


def collect_technologies(entries: list[dict]) -> list[str]:
    """Every entry's ``tech`` (comma separated string or list), deduplicated
    case-insensitively, first occurrence wins."""
    seen: set[str] = set()
    technologies: list[str] = []
    for entry in entries:
        tech = entry.get("tech") or ""
        items = tech if isinstance(tech, list) else str(tech).split(",")
        for item in items:
            item = str(item).strip()
            if item and item.lower() not in seen:
                seen.add(item.lower())
                technologies.append(item)
    return technologies


def render_technologies(categories: list[tuple[str, list[str]]]) -> str:
    """``\\cvitem{Category}{a, b, c}`` lines; empty string when there is nothing."""
    return "\n".join(
        f"  \\cvitem{{{tex_escape(name)}}}{{{{\\color{{muted}}{', '.join(tex_escape(t) for t in techs)}}}}}"
        for name, techs in categories
        if techs
    )


# --------------------------------------------------------------------------- sections


def _section_block(title: str, body: str) -> str:
    return (
        f"\\begin{{cvsectionblock}}{{{title}}}\n"
        "\\begin{addmargin}[0.5cm]{0cm}\n"
        f"{body}\n"
        "\\end{addmargin}\n"
        "\\end{cvsectionblock}"
    )


def render_education(education: list[dict], certifications: list[str]) -> str:
    """ "Education & Certifications" section, or an empty string when both are empty."""
    education = [e for e in education if (e.get("degree") or e.get("institution"))]
    certifications = [c.strip() for c in certifications if c and c.strip()]
    if not education and not certifications:
        return ""
    lines: list[str] = []
    for i, entry in enumerate(education):
        if i:
            lines.append("  \\vspace{6pt}")
        start, end = tex_escape(entry.get("date_start")), tex_escape(entry.get("date_end"))
        dates = " -- ".join(d for d in (start, end) if d)
        head = f"  \\textbf{{{tex_escape(entry.get('degree'))}}}"
        if dates:
            head += f" \\hfill {{\\color{{muted}}\\small {dates}}}"
        lines.append(head + "\\par")
        if entry.get("institution"):
            lines.append(f"  {{\\color{{muted}}\\itshape {tex_escape(entry['institution'])}\\par}}")
        if entry.get("note"):
            lines.append(f"  {{\\footnotesize\\color{{muted}}\\itshape {tex_escape(entry['note'])}\\par}}")
    if certifications:
        if education:
            lines.append("  \\vspace{6pt}")
        lines.append("  \\textbf{Professional Certifications}\\par")
        lines.append("  \\vspace{2pt}")
        lines.append("  \\begin{itemize}")
        lines.extend(f"    \\item {tex_escape(c)}" for c in certifications)
        lines.append("  \\end{itemize}")
    if education and certifications:
        title = "Education \\& Certifications"
    elif education:
        title = "Education"
    else:
        title = "Certifications"
    return _section_block(title, "\n".join(lines))


def render_languages(languages: list[dict]) -> str:
    languages = [lang for lang in languages if lang.get("language")]
    if not languages:
        return ""
    lines = [
        f"  \\cvitem{{{tex_escape(lang['language'])}}}{{{{\\color{{muted}}{tex_escape(lang.get('level'))}}}}}"
        for lang in languages
    ]
    return _section_block("Languages", "\n".join(lines))


def render_technologies_section(categories: list[tuple[str, list[str]]]) -> str:
    body = render_technologies(categories)
    return _section_block("Technologies", body) if body else ""


def render_consent(text: str | None) -> str:
    """Consent clause in small muted type; paragraphs (blank-line separated) are kept."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    if not paragraphs:
        return ""
    body = "\\par\\vspace{4pt}".join(tex_escape(" ".join(p.split())) for p in paragraphs)
    return f"\\par\\vspace{{18pt}}\n\\begin{{cvblock}}\n  {{\\footnotesize\\color{{muted}} {body}\\par}}\n\\end{{cvblock}}"


# --------------------------------------------------------------------------- template


def fill_template(template: str, values: dict[str, str]) -> str:
    """Replace every placeholder of :data:`PLACEHOLDERS` (all occurrences); ``values`` must
    cover them all and the template must contain each at least once."""
    missing = [p for p in PLACEHOLDERS if p not in values]
    if missing:
        raise ValueError(f"no value for placeholder(s): {', '.join(missing)}")
    for placeholder in PLACEHOLDERS:
        if placeholder not in template:
            raise ValueError(f"template does not contain {placeholder}")
        template = template.replace(placeholder, values[placeholder])
    return template


def render_cv(
    *,
    template: str,
    details: dict,
    headline_role: str,
    core_technologies: list[str],
    summary: str,
    main: list[dict],
    early: list[dict],
    categories: list[tuple[str, list[str]]],
) -> str:
    """The complete ``.tex`` document."""
    name = " ".join(part for part in (details.get("first_name", ""), details.get("last_name", "")) if part).strip()
    return fill_template(
        template,
        {
            "__NAME__": tex_escape(name),
            "__HEADLINE__": render_headline(headline_role, core_technologies),
            "__PDF_SUBJECT__": tex_escape(headline_role),
            "__CONTACTS__": render_contacts(details),
            "__SUMMARY__": tex_escape(summary),
            "__ROLES__": render_roles(main, early),
            "__EDUCATION__": render_education(details.get("education") or [], details.get("certifications") or []),
            "__TECHNOLOGIES__": render_technologies_section(categories),
            "__LANGUAGES__": render_languages(details.get("languages") or []),
            "__CONSENT__": render_consent(details.get("consent_text")),
        },
    )


def load_template() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")
