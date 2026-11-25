"""Generating a CV tailored to one parsed job as a background (RQ) job.

``generate_cv(generated_cv_id)`` takes the ``generated_cvs`` row created by
``POST /api/cv/generate`` (status ``queued``), flips it to ``running`` and runs the
pipeline below; on success the row ends ``finished`` with the ``.tex``/``.pdf`` paths, on
any failure ``failed`` with the error, and the exception is re-raised so RQ records the
failure as well.

Pipeline (a port of the ``building_cv`` reference scripts):

1. **Relevance.** Every ``work_history`` row is scored against the job description with
   one Jev decision (``OpenRouterService.decide``) - the probability that the role is
   relevant experience for the job.
2. **Timeline.** ``app.tasks.cv.history.build_coherent_history`` picks which roles are
   listed in full (``main``) and which are condensed (``early``), resolving overlapping
   periods and pushing old, non-relevant roles out of the main listing. Roles held one after
   another at one employer (promotions, see ``app.services.career``) form a tenure, listed
   as one employer block.
3. **Tailoring.** For every main role the chat model rewrites the context (max 3
   sentences) and reorders/filters its technologies for the job; every early role is
   condensed to a single sentence. A failed call keeps the original text and is reported
   in the row's ``pipeline.warnings``.
4. **Headline.** Four more chat calls: group the candidate's technologies into
   categories, write the summary, pick the headline role and the core technologies.
5. **Typesetting.** ``app.tasks.cv.render.render_cv`` fills the template with the
   candidate's details (``candidate_details``) and ``app.tasks.latex.compile_latex``
   builds the PDF under ``settings.cv_root / <id>``.

Independent OpenRouter calls run concurrently (``settings.cv_max_workers``); every call
gets its own database session because sessions are not thread-safe. Only a missing API
key (``OpenRouterNotConfigured``) aborts a step outright; other call failures are retried
once and then fall back as described above.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app import llm_calls
from app.config import Settings, get_settings
from app.db import init_db, session_factory
from app.llm_calls import ChatCall, DecisionCall
from app.models import (
    CandidateDetails,
    GeneratedCV,
    JobParseResult,
    OpenRouterCall,
    WorkHistoryEntry,
)
from app.services.career import previous_role_ids, tenure_ids
from app.services.openrouter import (
    OpenRouterError,
    OpenRouterNotConfigured,
    OpenRouterService,
)
from app.tasks.cv import prompts
from app.tasks.cv.history import Role, build_coherent_history
from app.tasks.cv.render import collect_technologies, load_template, render_cv
from app.tasks.latex import compile_latex

log = logging.getLogger(__name__)


TEX_NAME = "cv.tex"

T = TypeVar("T")


class CvGenerationError(RuntimeError):
    """The CV cannot be generated with the data at hand (no work history, no name, ...)."""


# --------------------------------------------------------------------------- inputs


def job_description_text(parsed: JobParseResult) -> str:
    """Title, company and description of the parsed job as one text block."""
    company = parsed.company.name if parsed.company is not None else ""
    head = " at ".join(part for part in (parsed.title or "", company) if part)
    return "\n\n".join(part for part in (head, (parsed.description or "").strip()) if part)


def load_roles(session: Session, today: date | None = None) -> list[Role]:
    """The positions of the work history as ``Role``s, newest first; pending positions
    (starting after ``today``), education and certificates are left out. Roles that continue
    an earlier one at the same employer carry its ``tenure`` (``None`` for a lone role)."""
    entries = _started(session, WorkHistoryEntry.KIND_JOB, today)
    previous = previous_role_ids(entries)
    tenures = tenure_ids(entries)
    in_chain = set(previous) | set(previous.values())
    return [
        Role.from_dates(
            employer=e.employer,
            role=e.role,
            date_start=e.date_start,
            date_end=e.date_end,
            today=today,
            location=e.location,
            tech=list(e.tech or []),
            context=e.context,
            id=e.id,
            tenure=tenures[e.id] if e.id in in_chain else None,
            transition=e.transition if e.id in previous else None,
        )
        for e in entries
    ]


def _started(session: Session, kind: str, today: date | None) -> Sequence[WorkHistoryEntry]:
    """Timeline entries of ``kind`` that started by ``today``, newest first."""
    return session.scalars(
        select(WorkHistoryEntry)
        .where(WorkHistoryEntry.kind == kind, WorkHistoryEntry.date_start <= (today or date.today()))
        .order_by(WorkHistoryEntry.date_start.desc(), WorkHistoryEntry.id.desc())
    ).all()


def _cv_month(value: date) -> str:
    return value.strftime("%b %Y")


def certificate_line(entry: WorkHistoryEntry) -> str:
    """``AWS Solutions Architect — Amazon (Mar 2021)``; a certificate with a duration shows
    its range (``Jan 2020 – Jun 2020``)."""
    when = _cv_month(entry.date_start)
    if entry.date_end is not None and entry.date_end != entry.date_start:
        when = f"{when} – {_cv_month(entry.date_end)}"
    head = " — ".join(part for part in (entry.role, entry.employer) if part)
    return f"{head} ({when})"


def load_education(session: Session, today: date | None = None) -> dict[str, list]:
    """The ``education`` / ``certifications`` blocks of the CV details, built from the
    education and certificate entries of the career timeline that started by ``today``."""
    education = [
        {
            "degree": e.role,
            "institution": e.employer,
            "date_start": _cv_month(e.date_start),
            "date_end": _cv_month(e.date_end) if e.date_end else "present",
            "note": e.context or "",
        }
        for e in _started(session, WorkHistoryEntry.KIND_EDUCATION, today)
    ]
    certifications = [certificate_line(e) for e in _started(session, WorkHistoryEntry.KIND_CERTIFICATE, today)]
    return {"education": education, "certifications": certifications}


def load_details(session: Session) -> CandidateDetails | None:
    return session.scalar(select(CandidateDetails).order_by(CandidateDetails.id.desc()).limit(1))


def details_dict(details: CandidateDetails) -> dict[str, Any]:
    return {
        "first_name": details.first_name,
        "last_name": details.last_name,
        "email": details.email,
        "phone": details.phone,
        "website": details.website,
        "github": details.github,
        "linkedin": details.linkedin,
        "location": details.location,
        "languages": list(details.languages or []),
        "consent_text": details.consent_text,
    }


def check_details(details: CandidateDetails | None) -> None:
    """Raise :class:`CvGenerationError` unless the candidate's name is known."""
    if details is None or not (details.first_name.strip() and details.last_name.strip()):
        raise CvGenerationError("missing candidate details: fill in your first and last name on the Candidate profile tab")


# --------------------------------------------------------------------------- LLM access


class Llm:
    """Runs OpenRouter calls for one generation, concurrently and each on its own session.

    ``chat`` and ``decide`` return ``None`` when the call fails (after one retry); the
    pipeline steps then fall back. A missing API key propagates as
    :class:`OpenRouterNotConfigured` since nothing can succeed without it.
    """

    ATTEMPTS = 2

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.call_ids: list[int] = []
        """``openrouter_calls.id`` of every successful call, so the cost can be summed."""
        self._lock = threading.Lock()

    def _record(self, call_id: int) -> None:
        with self._lock:
            self.call_ids.append(call_id)

    def cost(self, session: Session) -> tuple[float, int]:
        """``(total USD cost, number of calls)`` of the calls made so far."""
        if not self.call_ids:
            return 0.0, 0
        total = session.scalar(
            select(func.coalesce(func.sum(OpenRouterCall.cost), 0.0)).where(OpenRouterCall.id.in_(self.call_ids))
        )
        return float(total or 0.0), len(self.call_ids)

    def run_all(self, calls: Sequence[Callable[[OpenRouterService], T]]) -> list[T]:
        """Run every ``call(service)`` in a thread pool and return the results in order."""
        if not calls:
            return []
        workers = max(1, min(self.settings.cv_max_workers, len(calls)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(self._with_service, calls))

    @staticmethod
    def _with_service(call: Callable[[OpenRouterService], T]) -> T:
        with session_factory()() as session:
            return call(OpenRouterService(session))

    def chat(
        self,
        service: OpenRouterService,
        system: str,
        user: str,
        *,
        call: ChatCall,
        temperature: float,
    ) -> str | None:
        for attempt in range(1, self.ATTEMPTS + 1):
            try:
                result = service.chat(
                    user,
                    system=system,
                    call=call,
                    temperature=temperature,
                )
            except OpenRouterNotConfigured:
                raise
            except OpenRouterError as exc:
                log.warning("%s call failed (attempt %d): %s", call.key, attempt, exc)
                continue
            self._record(result.call_id)
            text = (result.text or "").strip()
            if text:
                return text
            log.warning("%s call returned an empty answer (attempt %d)", call.key, attempt)
        return None

    def decide(
        self,
        service: OpenRouterService,
        state: dict[str, Any],
        questions: dict[str, dict[str, Any]],
        *,
        call: DecisionCall,
    ) -> dict[str, dict[str, Any]] | None:
        for attempt in range(1, self.ATTEMPTS + 1):
            try:
                result = service.decide(state=state, questions=questions, call=call)
            except OpenRouterNotConfigured:
                raise
            except OpenRouterError as exc:
                log.warning("%s call failed (attempt %d): %s", call.key, attempt, exc)
                continue
            self._record(result.call_id)
            return result.answers
        return None


def _strip_fences(text: str) -> str:
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())


def _clean_line(text: str) -> str:
    return " ".join(text.strip().strip("\"'").split())


# --------------------------------------------------------------------------- steps


def score_relevance(llm: Llm, roles: list[Role], job_description: str, warnings: list[str]) -> None:
    """Step 1: set ``role.relevance`` for every role (``0.5`` when the call failed)."""
    description = job_description[: prompts.JEV_MAX_DESCRIPTION_CHARS]

    def one(role: Role) -> Callable[[OpenRouterService], float | None]:
        past_role = {k: v for k, v in role.to_dict().items() if k != "relevance"}

        def call(service: OpenRouterService) -> float | None:
            answers = llm.decide(
                service,
                {"past_role": past_role, "job_description": description},
                prompts.RELEVANCE_QUESTIONS,
                call=llm_calls.CV_RELEVANCE,
            )
            if answers is None:
                return None
            answer = answers.get(prompts.RELEVANCE_QUESTION_NAME) or {}
            if answer.get("type") != "noul":
                log.warning("unexpected relevance answer for %s: %r", role.label, answer)
                return None
            try:
                return float(answer["noul"])
            except (KeyError, TypeError, ValueError):
                return None

        return call

    scores = llm.run_all([one(role) for role in roles])
    for role, score in zip(roles, scores, strict=True):
        if score is None:
            warnings.append(f"relevance of {role.label} could not be scored; assumed 0.5")
            role.relevance = 0.5
        else:
            role.relevance = score
        log.info("relevance %.2f  %s", role.relevance, role.label)


def _position_message(entry: dict, job_description: str, heading: str) -> str:
    position = {k: v for k, v in entry.items() if k != "relevance"}
    return f"JOB DESCRIPTION:\n{job_description}\n\n{heading}:\n{json.dumps(position, indent=2, ensure_ascii=False)}"


def tailor_main_roles(llm: Llm, entries: list[dict], job_description: str, warnings: list[str]) -> list[dict]:
    """Step 3a: rewrite ``context`` and ``tech`` of every main role for the job."""

    def context_call(entry: dict) -> Callable[[OpenRouterService], str | None]:
        message = _position_message(entry, job_description, "WORK HISTORY POSITION")
        return lambda service: llm.chat(
            service, prompts.CONTEXT_SYSTEM_PROMPT, message, call=llm_calls.CV_CONTEXT, temperature=0.3
        )

    def tech_call(entry: dict) -> Callable[[OpenRouterService], str | None]:
        subset = {k: entry.get(k) for k in ("tech", "context")}
        message = (
            f"JOB DESCRIPTION:\n{job_description}\n\n"
            f"TECHNOLOGY AND CONTEXT:\n{json.dumps(subset, indent=2, ensure_ascii=False)}"
        )
        return lambda service: llm.chat(
            service, prompts.TECH_SYSTEM_PROMPT, message, call=llm_calls.CV_TECH, temperature=0.3
        )

    results = llm.run_all([context_call(e) for e in entries] + [tech_call(e) for e in entries])
    contexts, techs = results[: len(entries)], results[len(entries) :]
    tailored = []
    for entry, context, tech in zip(entries, contexts, techs, strict=True):
        label = f"{entry.get('role')} @ {entry.get('employer')}"
        new_entry = dict(entry)
        if context is None:
            warnings.append(f"context of {label} could not be tailored; kept the original")
        else:
            new_entry["context"] = _clean_line(context)
        if tech is None:
            warnings.append(f"technologies of {label} could not be tailored; kept the original")
        else:
            new_entry["tech"] = ", ".join(t.strip() for t in _clean_line(tech).split(",") if t.strip()) or entry.get(
                "tech", ""
            )
        tailored.append(new_entry)
    return tailored


def condense_early_roles(llm: Llm, entries: list[dict], job_description: str, warnings: list[str]) -> list[dict]:
    """Step 3b: condense every early role's context into one sentence."""

    def call(entry: dict) -> Callable[[OpenRouterService], str | None]:
        message = _position_message(entry, job_description, "EARLIER POSITION")
        return lambda service: llm.chat(
            service, prompts.EARLY_SYSTEM_PROMPT, message, call=llm_calls.CV_EARLY, temperature=0.3
        )

    results = llm.run_all([call(e) for e in entries])
    condensed = []
    for entry, sentence in zip(entries, results, strict=True):
        new_entry = dict(entry)
        if sentence is None:
            warnings.append(
                f"context of {entry.get('role')} @ {entry.get('employer')} could not be condensed; kept the original"
            )
        else:
            new_entry["context"] = _clean_line(sentence)
        condensed.append(new_entry)
    return condensed


def _parse_categories(reply: str) -> list[tuple[str, list[str]]] | None:
    try:
        data = json.loads(_strip_fences(reply))
    except ValueError:
        return None
    if not isinstance(data, list):
        return None
    categories = []
    for item in data:
        if not isinstance(item, dict):
            return None
        name = str(item.get("category") or "").strip()
        techs = [str(t).strip() for t in item.get("technologies") or [] if str(t).strip()]
        if name and techs:
            categories.append((name, techs))
    return categories or None


def categorize_technologies(
    llm: Llm,
    service: OpenRouterService,
    technologies: list[str],
    job_description: str,
    warnings: list[str],
) -> list[tuple[str, list[str]]]:
    """Group the technologies into job-relevant categories; one flat category on failure.
    Nothing is dropped or invented: unknown names are ignored, missing ones appended."""
    fallback = [("Technologies", technologies)]
    if not technologies:
        return []
    message = f"JOB DESCRIPTION:\n{job_description}\n\nTECHNOLOGIES:\n{json.dumps(technologies, ensure_ascii=False)}"
    reply = llm.chat(service, prompts.CATEGORIES_SYSTEM_PROMPT, message, call=llm_calls.CV_CATEGORIES, temperature=0.2)
    categories = _parse_categories(reply) if reply else None
    if categories is None:
        warnings.append("technologies could not be categorised; listed in one category")
        return fallback

    given = {t.lower(): t for t in technologies}
    used: set[str] = set()
    cleaned: list[tuple[str, list[str]]] = []
    for name, techs in categories:
        kept = []
        for tech in techs:
            key = tech.lower()
            if key in given and key not in used:
                used.add(key)
                kept.append(tech)
        if kept:
            cleaned.append((name, kept))
    missing = [t for k, t in given.items() if k not in used]
    if missing:
        if cleaned:
            cleaned[-1] = (cleaned[-1][0], cleaned[-1][1] + missing)
        else:
            cleaned = fallback
    return cleaned


def generate_summary(
    llm: Llm,
    service: OpenRouterService,
    history: list[dict],
    job_description: str,
    warnings: list[str],
) -> str:
    message = f"JOB DESCRIPTION:\n{job_description}\n\nWORK HISTORY:\n{json.dumps(history, ensure_ascii=False, indent=1)}"
    reply = llm.chat(service, prompts.SUMMARY_SYSTEM_PROMPT, message, call=llm_calls.CV_SUMMARY, temperature=0.2)
    if not reply:
        warnings.append("summary could not be generated; left empty")
        return ""
    summary = _clean_line(reply)
    words = summary.split()
    if len(words) > prompts.SUMMARY_MAX_WORDS:
        summary = " ".join(words[: prompts.SUMMARY_MAX_WORDS]).rstrip(",;:") + "."
    return summary


def pick_headline_role(
    llm: Llm,
    service: OpenRouterService,
    history: list[dict],
    job_description: str,
    warnings: list[str],
) -> str:
    """Job-tailored, experience-consistent headline title; the latest role on failure."""
    fallback = str((history[0].get("role") if history else "") or "").strip()
    message = f"JOB DESCRIPTION:\n{job_description}\n\nWORK HISTORY:\n{json.dumps(history, ensure_ascii=False, indent=1)}"
    reply = llm.chat(service, prompts.ROLE_SYSTEM_PROMPT, message, call=llm_calls.CV_ROLE, temperature=0.2)
    if not reply:
        warnings.append("headline role could not be picked; used the latest role")
        return fallback
    role = _clean_line(reply).rstrip(".")
    if len(role.split()) > prompts.ROLE_MAX_WORDS:
        warnings.append(f"headline role {role!r} is too long; used the latest role")
        return fallback
    return role


def pick_core_technologies(
    llm: Llm,
    service: OpenRouterService,
    technologies: list[str],
    job_description: str,
    warnings: list[str],
) -> list[str]:
    """The 1-2 technologies that best match the job; the first ones listed on failure."""
    fallback = technologies[: prompts.CORE_TECH_MAX]
    if not technologies:
        return []
    message = f"JOB DESCRIPTION:\n{job_description}\n\nTECHNOLOGIES:\n{json.dumps(technologies, ensure_ascii=False)}"
    reply = llm.chat(service, prompts.CORE_TECH_SYSTEM_PROMPT, message, call=llm_calls.CV_CORE_TECH, temperature=0.2)
    if not reply:
        warnings.append("core technologies could not be picked; used the first ones listed")
        return fallback
    text = _strip_fences(reply)
    try:
        data = json.loads(text)
    except ValueError:
        data = [t.strip() for t in text.split(",")]
    if not isinstance(data, list):
        warnings.append("core technologies reply was not a list; used the first ones listed")
        return fallback
    given = {t.lower(): t for t in technologies}
    chosen: list[str] = []
    for item in data:
        tech = given.get(str(item).strip().lower())
        if tech and tech not in chosen:
            chosen.append(tech)
        if len(chosen) == prompts.CORE_TECH_MAX:
            break
    if not chosen:
        warnings.append("core technologies reply matched nothing; used the first ones listed")
        return fallback
    return chosen


# --------------------------------------------------------------------------- pipeline


def run_pipeline(session: Session, cv: GeneratedCV, *, settings: Settings | None = None) -> dict[str, Any]:
    """Run every step for ``cv`` and return what to store on the row::

        {
            "headline_role": str, "core_technologies": [str], "summary": str,
            "tex_path": str, "pdf_path": str, "pipeline": {...},
        }

    Raises :class:`CvGenerationError` for missing inputs, ``OpenRouterNotConfigured`` for a
    missing API key and ``LatexCompileError`` when pdflatex fails.
    """
    settings = settings or get_settings()
    today = date.today()
    warnings: list[str] = []

    parsed = session.get(JobParseResult, cv.job_parse_result_id, options=[joinedload(JobParseResult.company)])
    if parsed is None:
        raise CvGenerationError("the parsed job no longer exists")
    job_description = job_description_text(parsed)
    if not job_description.strip():
        raise CvGenerationError("the parsed job has no description")

    roles = load_roles(session, today)
    if not roles:
        raise CvGenerationError("missing work history: add at least one position first")
    details = load_details(session)
    check_details(details)
    assert details is not None

    llm = Llm(settings)

    # 1. relevance
    score_relevance(llm, roles, job_description, warnings)

    # 2. timeline
    history = build_coherent_history(
        roles,
        max_entries=settings.cv_max_entries,
        min_entries=settings.cv_min_entries,
        high_relevance=settings.cv_high_relevance,
        irrelevant_relevance=settings.cv_irrelevant_relevance,
        min_months=settings.cv_min_months,
    )
    main_entries = [r.to_dict(today) for r in history.main]
    early_entries = [r.to_dict(today) for r in history.early]
    for line in history.log:
        log.info("timeline: %s", line)

    # 3. tailoring
    main_entries = tailor_main_roles(llm, main_entries, job_description, warnings)
    early_entries = condense_early_roles(llm, early_entries, job_description, warnings)

    # Which listed roles share an employer block; added after tailoring so the ids never
    # reach the prompts.
    main_entries = [entry | {"tenure": role.tenure} for entry, role in zip(main_entries, history.main, strict=True)]
    early_entries = [entry | {"tenure": role.tenure} for entry, role in zip(early_entries, history.early, strict=True)]

    # 4. headline
    technologies = collect_technologies(main_entries)
    prompt_history = [{k: v for k, v in e.items() if k not in ("relevance", "tenure")} for e in main_entries]
    categories, summary, headline_role, core_technologies = llm.run_all(
        [
            lambda s: categorize_technologies(llm, s, technologies, job_description, warnings),
            lambda s: generate_summary(llm, s, prompt_history, job_description, warnings),
            lambda s: pick_headline_role(llm, s, prompt_history, job_description, warnings),
            lambda s: pick_core_technologies(llm, s, technologies, job_description, warnings),
        ]
    )

    # 5. typesetting
    tex = render_cv(
        template=load_template(),
        details=details_dict(details) | load_education(session, today),
        headline_role=headline_role,
        core_technologies=core_technologies,
        summary=summary,
        main=main_entries,
        early=early_entries,
        categories=categories,
    )
    out_dir = cv_dir(settings, cv.id)
    out_dir.mkdir(parents=True, exist_ok=True)
    tex_path = out_dir / TEX_NAME
    tex_path.write_text(tex, encoding="utf-8")
    cost, call_count = llm.cost(session)

    def with_original(entries: list[dict], source: list[Role]) -> list[dict]:
        """Pipeline copy of the tailored entries: adds the ``work_history`` id and the
        text the LLM started from, so the UI can show what was changed."""
        return [
            {
                **entry,
                "id": role.id,
                "months": role.length,
                "original_context": role.context,
                "original_tech": ", ".join(role.tech),
            }
            for entry, role in zip(entries, source, strict=True)
        ]

    pipeline = {
        "job_description_chars": len(job_description),
        "cost": cost,
        "openrouter_calls": call_count,
        "thresholds": {
            "max_entries": settings.cv_max_entries,
            "min_entries": settings.cv_min_entries,
            "high_relevance": settings.cv_high_relevance,
            "irrelevant_relevance": settings.cv_irrelevant_relevance,
            "min_months": settings.cv_min_months,
        },
        "relevance": [
            {
                "id": r.id,
                "employer": r.employer,
                "role": r.role,
                "relevance": round(r.relevance, 4),
                "date_start": r.date_start,
                "date_end": r.date_end_label(today),
                "months": r.length,
            }
            for r in roles
        ],
        "main": with_original(main_entries, history.main),
        "early": with_original(early_entries, history.early),
        "categories": [[name, techs] for name, techs in categories],
        "timeline_log": history.log,
        "warnings": warnings,
    }
    (out_dir / "pipeline.json").write_text(json.dumps(pipeline, indent=2, ensure_ascii=False), encoding="utf-8")
    compiled = compile_latex(str(tex_path), out_dir=str(out_dir))
    pipeline["latex_log_tail"] = compiled["log_tail"]

    return {
        "headline_role": headline_role,
        "core_technologies": core_technologies,
        "summary": summary,
        "tex_path": str(tex_path),
        "pdf_path": compiled["pdf"],
        "pipeline": pipeline,
    }


def cv_dir(settings: Settings, generated_cv_id: int) -> Path:
    return settings.cv_root.resolve() / str(generated_cv_id)


def generate_cv(generated_cv_id: int) -> dict[str, Any]:
    """RQ entry point: run :func:`run_pipeline` for ``generated_cvs.id == generated_cv_id``
    and record the outcome on the row.

    Returns ``{"generated_cv_id", "status", "pdf_path", "warnings"}``. Raises after marking
    the row ``failed`` so RQ records the failure too.
    """
    init_db()
    with session_factory()() as session:
        cv = session.get(GeneratedCV, generated_cv_id)
        if cv is None:
            raise ValueError(f"unknown generated cv: {generated_cv_id}")
        if cv.status == GeneratedCV.STATUS_FINISHED:
            log.info("Generated CV %d was already finished", cv.id)
            return {
                "generated_cv_id": cv.id,
                "status": cv.status,
                "pdf_path": cv.pdf_path,
                "warnings": (cv.pipeline or {}).get("warnings", []),
            }

        cv.status = GeneratedCV.STATUS_RUNNING
        cv.started_at = datetime.now(UTC)
        cv.error = None
        session.commit()

        try:
            result = run_pipeline(session, cv)
        except Exception as exc:
            session.rollback()
            cv = session.get(GeneratedCV, generated_cv_id)
            if cv is not None:
                cv.status = GeneratedCV.STATUS_FAILED
                cv.error = f"{type(exc).__name__}: {exc}"
                cv.finished_at = datetime.now(UTC)
                session.commit()
            log.exception("Generating CV %d failed", generated_cv_id)
            raise

        cv.status = GeneratedCV.STATUS_FINISHED
        cv.finished_at = datetime.now(UTC)
        cv.headline_role = result["headline_role"]
        cv.core_technologies = result["core_technologies"]
        cv.summary = result["summary"]
        cv.tex_path = result["tex_path"]
        cv.pdf_path = result["pdf_path"]
        cv.pipeline = result["pipeline"]
        session.commit()
        log.info("Generated CV %d: %s", cv.id, cv.pdf_path)
        return {
            "generated_cv_id": cv.id,
            "status": cv.status,
            "pdf_path": cv.pdf_path,
            "warnings": result["pipeline"]["warnings"],
        }
