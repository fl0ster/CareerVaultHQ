"""Scoring parsed jobs against the current candidate profile as a background (RQ) job.

Both entry points take the current ``CandidateProfile`` (first regenerated from the work
history when it is missing or stale, see ``app.services.candidate_profile``), ask the OpenRouter
decisions API (``OpenRouterService.decide``) a single ``noul`` question per job and store
the probability of "yes" in ``job_evaluations``:

* ``evaluate_pending_jobs(limit)`` - every ``JobParseResult`` without a ``JobEvaluation``
  for that profile yet (a periodic catch-up, e.g. from the scheduler).
* ``evaluate_parse_results(ids)`` - the given ``job_parse_results`` rows only (the parse
  task enqueues this for the job it just parsed).

Jobs are scored one by one and each result is committed on its own, so a failure (or a
worker restart) half-way through loses nothing: re-running picks up where it stopped.

The task is idempotent per (parsed job, profile) pair: a pair that already has a row in
``job_evaluations`` is never selected again, and the table's unique constraint guarantees
that even two runs overlapping in time cannot store the pair twice (the loser's insert is
discarded and counted under ``skipped``).

A failed OpenRouter call is recorded in ``job_evaluation_failures`` and the pair is only
retried after an exponential backoff (``evaluate_retry_backoff_seconds``), at most
``evaluate_max_attempts`` times, so a broken job or provider is not hammered on every run.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import init_db, session_factory
from app.models import CandidateProfile, JobEvaluation, JobEvaluationFailure, JobParseResult
from app.services.candidate_profile import current_profile
from app.services.openrouter import (
    OpenRouterError,
    OpenRouterNotConfigured,
    OpenRouterService,
)

log = logging.getLogger(__name__)

SOURCE = "tasks.evaluate"
"""``openrouter_calls.source`` label for calls made by this task."""

MAX_PARSE_AGE = timedelta(days=7)
"""Parse results older than this are not evaluated: the listing is probably gone and the
OpenRouter call would be wasted."""

QUESTION_NAME = "is_match"
QUESTIONS: dict[str, dict[str, Any]] = {
    QUESTION_NAME: {
        "type": "noul",
        "instructions": (
            "Is this job a good match for the candidate? Consider the candidate's skills, "
            "technologies, seniority and experience against what the job description "
            "requires. Ignore the salary and the location."
        ),
        "criteria": {
            "true": (
                "The candidate meets the core requirements of the role and the role is "
                "consistent with the candidate's experience and skill set."
            ),
            "false": (
                "The job requires skills, seniority or a specialisation the candidate "
                "clearly lacks, or the role is in a different field."
            ),
        },
    }
}


class NoCandidateProfile(RuntimeError):
    """``candidate_profiles`` is empty, so there is nothing to evaluate against."""


def _unevaluated_query(profile_id: int, *, now: datetime | None = None):
    """``JobParseResult`` rows parsed within ``MAX_PARSE_AGE``, without a ``JobEvaluation``
    for ``profile_id`` and not waiting out a failure backoff, oldest first."""
    now = now or datetime.now(UTC)
    evaluated = select(JobEvaluation.job_parse_result_id).where(JobEvaluation.candidate_profile_id == profile_id)
    backing_off = select(JobEvaluationFailure.job_parse_result_id).where(
        JobEvaluationFailure.candidate_profile_id == profile_id,
        or_(
            JobEvaluationFailure.attempts >= get_settings().evaluate_max_attempts,
            JobEvaluationFailure.next_attempt_at > now,
        ),
    )
    return (
        select(JobParseResult)
        .where(JobParseResult.id.not_in(evaluated))
        .where(JobParseResult.id.not_in(backing_off))
        .where(JobParseResult.parsed_at >= now - MAX_PARSE_AGE)
        .order_by(JobParseResult.id)
    )


def pending_parse_results(session: Session, profile_id: int, *, limit: int | None = None) -> list[JobParseResult]:
    """Up to ``limit`` parsed jobs not yet evaluated against ``profile_id``."""
    stmt = _unevaluated_query(profile_id)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt))


def unevaluated_among(session: Session, profile_id: int, parse_result_ids: list[int]) -> list[JobParseResult]:
    """Those of ``parse_result_ids`` not yet evaluated against ``profile_id``."""
    if not parse_result_ids:
        return []
    stmt = _unevaluated_query(profile_id).where(JobParseResult.id.in_(parse_result_ids))
    return list(session.scalars(stmt))


def build_state(profile: CandidateProfile, parsed: JobParseResult) -> dict[str, Any]:
    """``state`` object sent to the decisions API."""
    return {
        "candidate_profile": profile.content,
        "job": {
            "title": parsed.title or "",
            "company": parsed.company.name if parsed.company else "",
            "description": parsed.description or "",
        },
    }


def evaluate_one(service: OpenRouterService, profile: CandidateProfile, parsed: JobParseResult) -> JobEvaluation:
    """Ask OpenRouter about one job and return the (unsaved) ``JobEvaluation``."""
    decision = service.decide(state=build_state(profile, parsed), questions=QUESTIONS, source=SOURCE)
    return JobEvaluation(
        job_parse_result_id=parsed.id,
        candidate_profile_id=profile.id,
        match_probability=decision.noul(QUESTION_NAME),
        openrouter_call_id=decision.call_id,
    )


def _record_failure(session: Session, profile: CandidateProfile, parsed: JobParseResult, error: str) -> None:
    """Bump the failure row for the pair and push its ``next_attempt_at`` out
    exponentially: ``backoff * 2**(attempts-1)``."""
    settings = get_settings()
    failure = session.scalar(
        select(JobEvaluationFailure).where(
            JobEvaluationFailure.job_parse_result_id == parsed.id,
            JobEvaluationFailure.candidate_profile_id == profile.id,
        )
    )
    if failure is None:
        failure = JobEvaluationFailure(job_parse_result_id=parsed.id, candidate_profile_id=profile.id, attempts=0)
        session.add(failure)
    failure.attempts += 1
    failure.last_error = error[:2000]
    failure.last_attempt_at = datetime.now(UTC)
    failure.next_attempt_at = failure.last_attempt_at + timedelta(
        seconds=settings.evaluate_retry_backoff_seconds * 2 ** (failure.attempts - 1)
    )
    try:
        session.commit()
    except IntegrityError:  # a concurrent run recorded the same failure; theirs is enough
        session.rollback()


def _clear_failure(session: Session, profile: CandidateProfile, parsed: JobParseResult) -> None:
    session.execute(
        delete(JobEvaluationFailure).where(
            JobEvaluationFailure.job_parse_result_id == parsed.id,
            JobEvaluationFailure.candidate_profile_id == profile.id,
        )
    )


def _current_profile(session: Session) -> CandidateProfile:
    """The current profile, (re)generated from the work history first when needed."""
    profile, created = current_profile(session, OpenRouterService(session))
    if created and profile is not None:
        log.info("Generated candidate profile %d from the work history", profile.id)
    if profile is None:
        raise NoCandidateProfile("no candidate profile to evaluate jobs against")
    return profile


def evaluate_pending_jobs(limit: int | None = None) -> dict[str, Any]:
    """Score every parsed job not yet evaluated against the latest candidate profile.
    ``limit`` caps how many jobs are scored in this run (``None`` = all of them).
    Returns the summary described in :func:`_evaluate`."""
    init_db()
    with session_factory()() as session:
        profile = _current_profile(session)
        pending = pending_parse_results(session, profile.id, limit=limit)
        return _evaluate(session, profile, pending)


def evaluate_parse_results(parse_result_ids: list[int]) -> dict[str, Any]:
    """Score the given ``job_parse_results`` rows against the latest candidate profile.
    Rows already evaluated against that profile are left alone, so re-enqueueing the same
    ids is a no-op. Returns the summary described in :func:`_evaluate`."""
    init_db()
    with session_factory()() as session:
        profile = _current_profile(session)
        pending = unevaluated_among(session, profile.id, parse_result_ids)
        return _evaluate(session, profile, pending)


def _evaluate(session: Session, profile: CandidateProfile, pending: list[JobParseResult]) -> dict[str, Any]:
    """Score ``pending`` one by one, committing each ``JobEvaluation`` on its own.

    Returns::

        {
            "candidate_profile_id": <id of the profile used>,
            "pending": <jobs that needed scoring when the run started>,
            "evaluated": <jobs scored and saved>,
            "failed": <jobs whose OpenRouter call failed>,
            "skipped": <jobs another run evaluated meanwhile (nothing stored)>,
            "evaluations": [
                {"job_parse_result_id": .., "job_id": .., "match_probability": ..}, ...
            ],
        }

    A failing OpenRouter call skips that job: the failure is recorded and the job is
    retried after a backoff (see ``_record_failure``). Only a missing API key aborts the
    whole run.
    """
    log.info("Evaluating %d parsed job(s) against candidate profile %d", len(pending), profile.id)
    service = OpenRouterService(session)

    evaluations: list[dict[str, Any]] = []
    failed = 0
    skipped = 0
    for parsed in pending:
        try:
            evaluation = evaluate_one(service, profile, parsed)
        except OpenRouterNotConfigured:
            raise  # OPENROUTER_API_KEY missing: nothing will succeed, bail out
        except OpenRouterError as exc:
            failed += 1
            session.rollback()
            _record_failure(session, profile, parsed, f"{type(exc).__name__}: {exc}")
            log.warning("Evaluating parsed job %d (job %d) failed: %s", parsed.id, parsed.job_id, exc)
            continue
        session.add(evaluation)
        try:
            _clear_failure(session, profile, parsed)
            session.commit()
        except IntegrityError:
            # Another run scored this pair since we selected it; keep theirs.
            session.rollback()
            skipped += 1
            log.info(
                "Parsed job %d already evaluated against profile %d, skipping",
                parsed.id,
                profile.id,
            )
            continue
        evaluations.append(
            {
                "job_parse_result_id": parsed.id,
                "job_id": parsed.job_id,
                "match_probability": evaluation.match_probability,
            }
        )
        log.info(
            "Job %d (%r at %r): match probability %.3f",
            parsed.job_id,
            parsed.title,
            parsed.company.name if parsed.company else None,
            evaluation.match_probability,
        )

    return {
        "candidate_profile_id": profile.id,
        "pending": len(pending),
        "evaluated": len(evaluations),
        "failed": failed,
        "skipped": skipped,
        "evaluations": evaluations,
    }
