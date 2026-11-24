"""LLM enrichment of a shortlisted job as a background (RQ) job.

``parse_job`` only extracts the plain fields (title, company, description) so a scraped
job is scored as soon as possible. The costlier LLM extractions are only worth running
for a job the user wants: like the CV, they are queued when an application is created
for the job (it is accepted from the inbox and shortlisted, ``POST /api/applications``):

* ``extract_interview_steps`` -> ``job_parse_results.interview_steps``, then planned on
  the job's application as interview rounds (unless rounds are planned already);
* ``extract_technologies`` -> ``job_parse_results.technologies``.

A value that is already set (e.g. interview steps taken from a recruiter's e-mail, or a
previous enrichment) is kept, so re-running the task makes no OpenRouter calls for it. An
OpenRouter failure only leaves that value unset.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from rq import Queue
from sqlalchemy import select

from app.config import Settings, get_settings
from app.db import init_db, session_factory
from app.models import Application, JobParseResult
from app.services.applications import FINAL_STATUSES, plan_parsed_rounds
from app.tasks.parse.parse import store_interview_steps, store_technologies

log = logging.getLogger(__name__)

ENRICH_TIMEOUT = 300
"""RQ ``job_timeout``: up to four OpenRouter calls (three for the interview steps, one
for the technologies)."""


def enrich_job(job_parse_result_id: int) -> dict[str, Any]:
    """Extract the interview steps and technologies of a parsed job.

    Returns::

        {
            "job_parse_result_id": <id>,
            "job_id": <id of the Job>,
            "interview_steps": <number of rounds, None if not extracted>,
            "technologies": <number of technologies, None if not extracted>,
            "planned_rounds": <rounds planned on the job's application>,
        }
    """
    init_db()
    with session_factory()() as session:
        parsed = session.get(JobParseResult, job_parse_result_id)
        if parsed is None:
            raise ValueError(f"unknown job parse result: {job_parse_result_id}")

        if parsed.interview_steps is None:
            store_interview_steps(session, parsed)
        if parsed.technologies is None:
            store_technologies(session, parsed)

        planned = 0
        application = session.scalar(select(Application).where(Application.job_parse_result_id == parsed.id))
        current = application.current_event if application is not None else None
        if (
            application is not None
            and parsed.interview_steps
            and not application.plan  # never add to rounds already planned (by hand or not)
            and (current is None or current.status.key not in FINAL_STATUSES)
        ):
            plan_parsed_rounds(session, application, parsed)
            planned = len(parsed.interview_steps)
        session.commit()

        log.info(
            "Enriched job %d: %s interview steps, %s technologies, %d rounds planned",
            parsed.job_id,
            len(parsed.interview_steps) if parsed.interview_steps is not None else None,
            len(parsed.technologies) if parsed.technologies is not None else None,
            planned,
        )
        return {
            "job_parse_result_id": parsed.id,
            "job_id": parsed.job_id,
            "interview_steps": len(parsed.interview_steps) if parsed.interview_steps is not None else None,
            "technologies": len(parsed.technologies) if parsed.technologies is not None else None,
            "planned_rounds": planned,
        }


def enqueue_enrichment(queue: Queue, settings: Settings | None, parsed: JobParseResult) -> str | None:
    """Queue ``enrich_job`` for ``parsed`` (which must be committed) and return the RQ job
    id. An unreachable queue is logged, not raised: the caller's work already succeeded."""
    settings = settings or get_settings()
    try:
        rq_job = queue.enqueue(
            enrich_job,
            parsed.id,
            job_id=uuid.uuid4().hex,
            job_timeout=ENRICH_TIMEOUT,
            result_ttl=settings.job_result_ttl,
            failure_ttl=settings.job_result_ttl,
            meta={"job_parse_result_id": parsed.id, "job_id": parsed.job_id},
            description=f"enrich job {parsed.job_id}",
        )
    except Exception:
        log.exception("Could not enqueue enrichment of job %d", parsed.job_id)
        return None
    return rq_job.id
