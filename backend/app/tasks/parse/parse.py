"""Parsing a scraped job's raw HTML as a background (RQ) job.

The scrape task inserts a ``PendingJobParseRun`` row for every new ``Job`` and enqueues
``parse_job(pending_id)``. The task looks up the job's ``source.key`` module in
``app.tasks.scrape.sources`` and calls its ``parse_<field>(html, url)`` hook for every
field in ``FIELDS`` (currently ``title``, ``company`` and ``description``). ``title`` and
``description`` are stored verbatim in ``job_parse_results``; the raw ``company`` string is
never stored there but resolved through ``app.services.companies.resolve_company`` to a
canonical ``companies`` row whose id is written to ``job_parse_results.company_id``. The
pending row is then marked ``COMPLETED`` with the time the parse happened. The interview
rounds stated in the description are extracted by an LLM pipeline (``extract_interview_steps``)
into ``job_parse_results.interview_steps`` and the technologies it names by
``extract_technologies`` into ``job_parse_results.technologies``; an OpenRouter failure only
leaves them unset. Finally
``app.tasks.evaluate.evaluate_parse_results`` is enqueued for the parsed job so it gets
scored against the current candidate profile.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from types import ModuleType
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import init_db, session_factory
from app.models import Job, JobParseResult, PendingJobParseRun
from app.queue import get_queue
from app.services.companies import CompanyMatch, resolve_company
from app.services.openrouter import OpenRouterNotConfigured, OpenRouterService
from app.services.technologies import dedupe_technologies, technology_key
from app.tasks.evaluate import evaluate_parse_results
from app.tasks.scrape.sources import load_source

log = logging.getLogger(__name__)

EVALUATE_TIMEOUT = 300
"""RQ ``job_timeout`` for the evaluation enqueued after a parse (one OpenRouter call)."""


FIELDS = ("title", "company", "description")
"""Fields extracted by the source's ``parse_<field>(html, url)`` hook. All but ``company``
are columns of ``JobParseResult``; ``company`` is resolved to ``company_id``."""

TEXT_FIELDS = tuple(field for field in FIELDS if field != "company")
"""The fields of ``FIELDS`` stored verbatim on ``JobParseResult``."""


@dataclass(frozen=True)
class InterviewStep:
    """One interview round found in a job description. Maps to a planned
    ``ApplicationEvent`` (status ``INTERVIEW``, ``planned=True``): ``title`` ->
    ``ApplicationEvent.title``, ``duration_minutes`` -> ``ApplicationEvent.duration_minutes``;
    ``number`` gives the round order."""

    number: int
    title: str
    duration_minutes: int | None = None


@dataclass(frozen=True)
class InterviewStepsResult:
    """Outcome of ``extract_interview_steps``; ``steps`` is empty unless both Jev checks
    passed."""

    steps: list[InterviewStep]
    present_probability: float
    """Jev: probability that the text describes the interview process at all."""
    faithful_probability: float | None = None
    """Jev: probability that the extracted steps are stated in the text (``None`` when the
    extraction was not attempted or returned nothing)."""


INTERVIEW_STEPS_SOURCE = "tasks.parse.interview_steps"
INTERVIEW_STEPS_THRESHOLD = 0.5
"""Minimum Jev probability for both the presence and the faithfulness check."""
MAX_STEP_TITLE = 128

PRESENCE_QUESTION = "describes_interview_process"
PRESENCE_QUESTIONS: dict[str, dict[str, Any]] = {
    PRESENCE_QUESTION: {
        "type": "noul",
        "instructions": (
            "Does this job description describe the stages of the recruitment / interview "
            "process the candidate will go through (in any language)?"
        ),
        "criteria": {
            "true": (
                "The text names at least one concrete stage of the hiring process, e.g. an "
                "HR call, technical interview, home assignment, live coding, meeting with "
                "the team or a final interview, as a list, a sentence or a chain of steps."
            ),
            "false": (
                "The text only describes the role, requirements, benefits or company, or "
                "merely says that the candidate will be contacted / that only selected "
                "candidates will be reached, without naming any stages."
            ),
        },
    }
}

FAITHFUL_QUESTION = "steps_are_faithful"
FAITHFUL_QUESTIONS: dict[str, dict[str, Any]] = {
    FAITHFUL_QUESTION: {
        "type": "noul",
        "instructions": (
            "Do the extracted interview steps accurately reflect the recruitment process described in the job description?"
        ),
        "criteria": {
            "true": (
                "Every extracted step is stated in the text, they are in the order the text "
                "gives, no stated stage is missing and durations match the text."
            ),
            "false": (
                "A step is invented, a requirement/benefit was taken for a step, stages are "
                "missing or out of order, or a duration is not supported by the text."
            ),
        },
    }
}

EXTRACTION_SYSTEM = "You extract structured data from job descriptions. Answer with a single JSON object and nothing else."
EXTRACTION_PROMPT = """The job description below describes its recruitment process.
List the stages a candidate goes through, in order, as a JSON object
{{"steps": [{{"title": ..., "duration_minutes": ...}}, ...]}} where
- "title" is a short name of the stage in the language of the text (e.g. "HR call",
  "Technical interview", "Home assignment", "Rozmowa z HR"),
- "duration_minutes" is the stated length of the stage in minutes, or null when not stated.
Only include stages the text actually states; do not include the offer or the decision
itself unless the text presents it as a meeting. Do not guess.

{text}"""


def _strip_fences(text: str) -> str:
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())


def _steps_from_reply(reply: str) -> list[InterviewStep]:
    try:
        data = json.loads(_strip_fences(reply))
    except ValueError:
        return []
    raw_steps = data.get("steps") if isinstance(data, dict) else data
    if not isinstance(raw_steps, list):
        return []
    steps: list[InterviewStep] = []
    for item in raw_steps:
        if not isinstance(item, dict) or not isinstance(item.get("title"), str):
            continue
        title = " ".join(item["title"].split())[:MAX_STEP_TITLE]
        duration = item.get("duration_minutes")
        if isinstance(duration, bool) or not isinstance(duration, int | float) or duration <= 0:
            duration = None
        if title:
            steps.append(InterviewStep(len(steps) + 1, title, int(duration) if duration else None))
    return steps


def extract_interview_steps(
    service: OpenRouterService,
    text: str | None,
    *,
    source: str = INTERVIEW_STEPS_SOURCE,
    private: bool = False,
) -> InterviewStepsResult:
    """Interview rounds described in ``text`` (a job description, or any text about one such
    as a recruiter's e-mail), in three LLM steps:

    1. Jev ``noul``: does the text describe the recruitment process at all? Below
       ``INTERVIEW_STEPS_THRESHOLD`` nothing else is called and no steps are returned.
    2. Chat completion: extract the ordered stages as JSON.
    3. Jev ``noul``: are the extracted steps faithful to the text? Below the threshold the
       extraction is discarded.

    ``source`` labels the OpenRouter calls and ``private`` is passed to them (set it for
    personal data such as e-mails). OpenRouter errors propagate (``OpenRouterError``).
    """
    if not text or not text.strip():
        return InterviewStepsResult([], 0.0)

    present = service.decide(
        state={"job_description": text},
        questions=PRESENCE_QUESTIONS,
        source=source,
        private=private,
    ).noul(PRESENCE_QUESTION)
    if present < INTERVIEW_STEPS_THRESHOLD:
        return InterviewStepsResult([], present)

    reply = service.chat(
        EXTRACTION_PROMPT.format(text=text),
        system=EXTRACTION_SYSTEM,
        temperature=0,
        source=source,
        private=private,
    ).text
    steps = _steps_from_reply(reply)
    if not steps:
        return InterviewStepsResult([], present)

    faithful = service.decide(
        state={
            "job_description": text,
            "extracted_steps": [
                {"number": s.number, "title": s.title, "duration_minutes": s.duration_minutes} for s in steps
            ],
        },
        questions=FAITHFUL_QUESTIONS,
        source=source,
        private=private,
    ).noul(FAITHFUL_QUESTION)
    if faithful < INTERVIEW_STEPS_THRESHOLD:
        log.info("Discarded interview steps (faithfulness %.2f): %r", faithful, steps)
        return InterviewStepsResult([], present, faithful)
    return InterviewStepsResult(steps, present, faithful)


TECHNOLOGIES_SOURCE = "tasks.parse.technologies"
MAX_TECHNOLOGIES = 40
MAX_TECHNOLOGY_NAME = 64

TECHNOLOGIES_PROMPT = """List the technologies the job description below asks for or
mentions as part of the role's work: programming languages, frameworks, libraries,
databases, cloud platforms, tools, protocols and engines.
Answer with a JSON object {{"technologies": [{{"name": ..., "evidence": ...}}, ...]}} where
- "name" is the technology's name exactly as written in the text (when the text spells it
  several ways, the fullest spelling),
- "evidence" is a short fragment copied EXACTLY, character for character, from the text,
  that contains that name.
Rules:
- Only technologies literally named in the text. Never infer one from another (no
  "JavaScript" because of "React", no "Docker" because of "Kubernetes").
- Not soft skills, methodologies (Agile, Scrum), spoken languages, job titles, domains
  or generic words ("databases", "cloud", "frontend").
- Each technology once, even if spelled several ways.
- If unsure, leave it out. An empty list is a valid answer.

{text}"""


def _squash(text: str) -> str:
    return " ".join(text.lower().split())


MAX_NAME_WORDS = 4


def _names_in(fragment: str, key: str) -> bool:
    """Whether a run of whole words of ``fragment`` has the technology ``key`` (so
    "React.js," names React, but "Google" does not name Go and "C#" does not name C)."""
    words = [word.strip(",;:()[]{}\"'!?/") for word in fragment.split()]
    for start in range(len(words)):
        for end in range(start + 1, min(start + MAX_NAME_WORDS, len(words)) + 1):
            if technology_key(" ".join(words[start:end])) == key:
                return True
    return False


def _technologies_from_reply(reply: str, text: str) -> list[dict[str, str]]:
    """Grounded, de-duplicated technologies from the LLM reply. An item is kept only when
    its ``evidence`` occurs verbatim in ``text`` and names the technology; everything
    else is dropped as possibly hallucinated."""
    try:
        data = json.loads(_strip_fences(reply))
    except ValueError:
        return []
    items = data.get("technologies") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    haystack = _squash(text)
    grounded: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name, evidence = item.get("name"), item.get("evidence")
        if not isinstance(name, str) or not isinstance(evidence, str):
            continue
        name = " ".join(name.split())[:MAX_TECHNOLOGY_NAME]
        fragment = _squash(evidence)
        key = technology_key(name)
        if not key or not fragment or fragment not in haystack:
            log.debug("Dropped technology %r: evidence %r not in text", name, evidence)
            continue
        if not _names_in(fragment, key):
            log.debug("Dropped technology %r: not named in %r", name, evidence)
            continue
        grounded.append(name)
    return dedupe_technologies(grounded)[:MAX_TECHNOLOGIES]


def extract_technologies(service: OpenRouterService, text: str | None) -> list[dict[str, str]]:
    """Technologies named in ``text`` (a job description) as
    ``[{"name": "React", "key": "react"}, ...]`` (``key`` from
    ``app.services.technologies.technology_key``), in one chat completion. Precision over
    recall: the model must quote where each technology appears and every quote is checked
    against the text, so nothing absent from the description is returned.

    OpenRouter errors propagate (``OpenRouterError``)."""
    if not text or not text.strip():
        return []
    reply = service.chat(
        TECHNOLOGIES_PROMPT.format(text=text),
        system=EXTRACTION_SYSTEM,
        temperature=0,
        source=TECHNOLOGIES_SOURCE,
    ).text
    return _technologies_from_reply(reply, text)


def store_technologies(session: Session, result: JobParseResult) -> list[dict[str, str]] | None:
    """Run ``extract_technologies`` on ``result.description`` and store them in
    ``result.technologies`` (not committed). Failures are logged and leave ``None``."""
    try:
        technologies = extract_technologies(OpenRouterService(session), result.description)
    except OpenRouterNotConfigured:
        log.info("OpenRouter not configured; technologies of job %d not extracted", result.job_id)
        result.technologies = None
        return None
    except Exception:
        log.exception("Extracting technologies of job %d failed", result.job_id)
        result.technologies = None
        return None
    result.technologies = technologies
    return technologies


def store_interview_steps(session: Session, result: JobParseResult) -> list[InterviewStep] | None:
    """Run ``extract_interview_steps`` on ``result.description`` and store the steps in
    ``result.interview_steps`` (not committed). An OpenRouter failure (or missing API key) is
    logged and leaves ``None``: the parse itself must not fail because of it."""
    try:
        steps = extract_interview_steps(OpenRouterService(session), result.description).steps
    except OpenRouterNotConfigured:
        log.info("OpenRouter not configured; interview steps of job %d not extracted", result.job_id)
        result.interview_steps = None
        return None
    except Exception:
        log.exception("Extracting interview steps of job %d failed", result.job_id)
        result.interview_steps = None
        return None
    result.interview_steps = [asdict(step) for step in steps]
    return steps


class JobParseError(RuntimeError):
    """The job cannot be parsed (no HTML, unknown source, source has no parser)."""


def _source_module(job: Job) -> ModuleType:
    try:
        return load_source(job.source.key)
    except ValueError as exc:
        raise JobParseError(str(exc)) from exc


def parse_field(job: Job, field: str, module: ModuleType | None = None) -> str:
    """Dispatch to ``app.tasks.scrape.sources.<job.source.key>.parse_<field>(html)``."""
    if not job.html:
        raise JobParseError(f"job {job.id} has no HTML to parse")
    module = module or _source_module(job)
    parser = getattr(module, f"parse_{field}", None)
    if parser is None:
        raise JobParseError(f"source {job.source.key!r} does not define parse_{field}")
    return parser(job.html)


def parse_title(job: Job) -> str:
    return parse_field(job, "title")


def parse_company(job: Job) -> str:
    return parse_field(job, "company")


def parse_description(job: Job) -> str:
    return parse_field(job, "description")


def parse_fields(job: Job) -> dict[str, str]:
    """``{field: value}`` for every field in ``FIELDS``."""
    module = _source_module(job)
    return {field: parse_field(job, field, module) for field in FIELDS}


def _save_result(session: Session, job: Job, values: dict[str, str]) -> tuple[JobParseResult, CompanyMatch | None]:
    """Upsert the ``JobParseResult`` of ``job``; the ``company`` value goes through the
    company ingestion pipeline and only the canonical ``company_id`` is stored."""
    result = session.scalar(select(JobParseResult).where(JobParseResult.job_id == job.id))
    if result is None:
        result = JobParseResult(job_id=job.id)
        session.add(result)
    for field in TEXT_FIELDS:
        setattr(result, field, values.get(field) or None)
    match = resolve_company(session, values.get("company", ""), source=job.source)
    result.company = match.company if match else None
    result.parsed_at = datetime.now(UTC)
    return result, match


def enqueue_evaluation(result: JobParseResult) -> str | None:
    """Enqueue ``evaluate_parse_results([result.id])`` (``result`` must be committed) and return the
    RQ job id. Failing to reach Redis is logged, not raised: the parse itself succeeded
    and a later ``evaluate_pending_jobs()`` run picks the job up anyway."""
    settings = get_settings()
    try:
        rq_job = get_queue().enqueue(
            evaluate_parse_results,
            [result.id],
            job_id=uuid.uuid4().hex,
            job_timeout=EVALUATE_TIMEOUT,
            result_ttl=settings.job_result_ttl,
            failure_ttl=settings.job_result_ttl,
            meta={"job_parse_result_id": result.id, "job_id": result.job_id},
            description=f"evaluate job {result.job_id}",
        )
    except Exception:
        log.exception("Could not enqueue evaluation of job %d", result.job_id)
        return None
    return rq_job.id


def parse_job(pending_id: int) -> dict[str, Any]:
    """Parse the job referenced by ``pending_job_parse_runs.id == pending_id``.

    Returns::

        {
            "pending_id": <id of the PendingJobParseRun row>,
            "job_id": <id of the parsed Job>,
            "source": "<source module name>",
            "title": "<extracted title>",
            "company": "<canonical company name, or None>",
            "company_id": <id of the canonical companies row, or None>,
            "company_match": "<alias | exact | fuzzy | new, or None>",
            "description_chars": <length of the extracted description>,
            "interview_steps": <number of interview rounds found, None if not extracted>,
            "technologies": <number of technologies found, None if not extracted>,
            "evaluate_job": "<RQ job id of the enqueued evaluation, or None>",
        }

    Raises on failure after marking the pending row ``FAILED`` so RQ records the job as
    failed and the error is visible in the database as well.
    """
    init_db()
    with session_factory()() as session:
        pending = session.get(PendingJobParseRun, pending_id)

        if pending is None:
            raise ValueError(f"unknown pending parse run: {pending_id}")

        job = session.get(Job, pending.job_id)
        if job is None:
            raise ValueError(f"pending parse run {pending_id} references a missing job")

        if pending.status == PendingJobParseRun.STATUS_COMPLETED:
            log.info("Job %d was already parsed", job.id)
            result = session.scalar(select(JobParseResult).where(JobParseResult.job_id == job.id))
            company = result.company if result else None
            return {
                "pending_id": pending.id,
                "job_id": job.id,
                "source": job.source.key,
                "title": result.title if result else None,
                "company": company.name if company else None,
                "company_id": company.id if company else None,
                "company_match": None,
                "description_chars": len(result.description or "") if result else 0,
                "interview_steps": len(result.interview_steps) if result and result.interview_steps is not None else None,
                "technologies": len(result.technologies) if result and result.technologies is not None else None,
                "evaluate_job": None,
            }

        try:
            values = parse_fields(job)
            result, match = _save_result(session, job, values)
        except Exception as exc:
            session.rollback()
            pending.status = PendingJobParseRun.STATUS_FAILED
            pending.error = f"{type(exc).__name__}: {exc}"
            pending.parsed_at = datetime.now(UTC)
            session.add(pending)
            session.commit()
            log.exception("Parsing job %d (%s) failed", job.id, job.link)
            raise

        pending.status = PendingJobParseRun.STATUS_COMPLETED
        pending.error = None
        pending.parsed_at = datetime.now(UTC)
        session.commit()
        steps = store_interview_steps(session, result)
        technologies = store_technologies(session, result)
        session.commit()
        evaluate_job_id = enqueue_evaluation(result)

        company = match.company if match else None
        log.info(
            "Parsed job %d (%s): %r at %r (company %s, %s), %d chars",
            job.id,
            job.link,
            values["title"],
            values["company"],
            company.id if company else None,
            match.match_kind if match else "none",
            len(values["description"]),
        )
        return {
            "pending_id": pending.id,
            "job_id": job.id,
            "source": job.source.key,
            "title": values["title"],
            "company": company.name if company else None,
            "company_id": company.id if company else None,
            "company_match": match.match_kind if match else None,
            "description_chars": len(values["description"]),
            "interview_steps": len(steps) if steps is not None else None,
            "technologies": len(technologies) if technologies is not None else None,
            "evaluate_job": evaluate_job_id,
        }
