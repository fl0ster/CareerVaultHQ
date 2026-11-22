"""Jobs stored in the database.

``GET /api/jobs?offset=0&limit=50`` returns a page of **evaluated** jobs: every
``job_evaluations`` row made against the latest candidate profile, together with the
job's parsed details (title, company, ...) and the scraped link. ``GET /api/jobs/{job_id}``
returns one job with its full parsed description.

The raw scraped rows (``jobs`` table, including the fetched html) are still available
under ``GET /api/jobs/raw`` and ``GET /api/jobs/raw/{job_id}``.

Every list endpoint returns ``total`` and ``has_more`` so clients can load further pages
progressively.

The Jobs tab uses two views of the same evaluations:

* ``GET /api/jobs/inbox`` - the *undecided relevant* jobs (score at or above
  ``settings.relevant_job_threshold``, no ``job_decisions`` row and no application), best
  match first. Its ``count`` drives the badge on the tab.
* ``GET /api/jobs/feed`` - everything else, newest job first, keyset-paginated by job id
  (``before`` for older pages, ``after`` to poll for newer jobs) so pages stay stable while
  jobs move out of the inbox and a re-scored job keeps its place.

``PUT /api/jobs/{job_id}/decision`` records ``accepted`` / ``rejected`` (creating an
application through ``POST /api/applications`` records ``accepted`` by itself).

A job keeps the score of an older candidate profile until it is re-scored; such an
evaluation is flagged ``outdated`` (the profile was built from an earlier work history) and
``POST /api/jobs/{job_id}/rescore`` enqueues scoring it against the latest profile.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator
from rq import Queue
from sqlalchemy import ColumnElement, Select, and_, func, not_, or_, select
from sqlalchemy.orm import Session, aliased, joinedload

from app.config import Settings, get_settings
from app.db import get_session
from app.models import (
    Application,
    CandidateProfile,
    Company,
    Job,
    JobDecision,
    JobEvaluation,
    JobParseResult,
    PendingJobParseRun,
    ScrapeSource,
)
from app.queue import get_queue
from app.services.applications import set_job_decision
from app.services.candidate_profile import current_profile_ids
from app.services.evaluations import newest_evaluations
from app.services.relevance import relevance
from app.tasks.evaluate import rescore_parse_results

log = logging.getLogger(__name__)

router = APIRouter()

RESCORE_TIMEOUT = 600
"""RQ ``job_timeout`` for a single-job re-score (may regenerate the profile first)."""

MAX_PAGE_SIZE = 200

SortOrder = Literal["newest", "match"]


# --- raw scraped jobs -----------------------------------------------------------------


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    link: str
    source: str
    """Key of the ``ScrapeSource`` (plugin module name) the job came from."""
    scrape_run_id: int | None
    has_html: bool = False

    @field_validator("source", mode="before")
    @classmethod
    def _source_key(cls, value: object) -> object:
        return value.key if isinstance(value, ScrapeSource) else value


class JobFull(JobOut):
    html: str | None


class JobPage(BaseModel):
    items: list[JobOut]
    total: int
    offset: int
    limit: int
    has_more: bool


def _to_out(job: Job) -> JobOut:
    out = JobOut.model_validate(job)
    out.has_html = bool(job.html)
    return out


@router.get("/raw", response_model=JobPage)
def list_raw_jobs(
    session: Annotated[Session, Depends(get_session)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
    source: str | None = None,
) -> JobPage:
    """Page of scraped jobs, newest first. Optionally filtered by scraper ``source``."""
    query = select(Job).options(joinedload(Job.source))
    count_query = select(func.count()).select_from(Job)
    if source:
        query = query.join(Job.source).where(ScrapeSource.key == source)
        count_query = count_query.join(Job.source).where(ScrapeSource.key == source)

    total = session.scalar(count_query) or 0
    jobs = session.scalars(query.order_by(Job.id.desc()).offset(offset).limit(limit)).all()
    return JobPage(
        items=[_to_out(j) for j in jobs],
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + len(jobs) < total,
    )


@router.get("/raw/{job_id}", response_model=JobFull)
def get_raw_job(job_id: int, session: Annotated[Session, Depends(get_session)]) -> JobFull:
    """A single scraped job including its full html content."""
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown job")
    return JobFull.model_validate(job)


# --- evaluated jobs -------------------------------------------------------------------


class EvaluationOut(BaseModel):
    id: int
    candidate_profile_id: int
    match_probability: float
    relevance: float
    """``match_probability`` mapped onto [-1, 1] around ``settings.relevant_job_threshold``
    (see ``relevance``): 0 at the threshold, positive above it. For display only."""
    model: str | None
    """Model that produced the score (from the ``openrouter_calls`` row), if still known."""
    outdated: bool = False
    """Scored against a profile built from an earlier work history than the latest profile;
    ``POST /api/jobs/{job_id}/rescore`` scores it again."""
    created_at: datetime


def _evaluation_out(evaluation: JobEvaluation | None, threshold: float, current_ids: set[int]) -> EvaluationOut | None:
    if evaluation is None:
        return None
    call = evaluation.openrouter_call
    return EvaluationOut(
        id=evaluation.id,
        candidate_profile_id=evaluation.candidate_profile_id,
        match_probability=evaluation.match_probability,
        relevance=relevance(evaluation.match_probability, threshold),
        model=call.model if call is not None else None,
        outdated=evaluation.candidate_profile_id not in current_ids,
        created_at=evaluation.created_at,
    )


class EvaluatedJobOut(BaseModel):
    """One evaluated job: the scraped row, its parsed details and the score."""

    id: int
    """``jobs.id``"""
    link: str
    source: str
    scrape_run_id: int | None
    has_html: bool
    title: str | None
    company: str | None
    company_id: int | None = None
    """``companies.id`` of the resolved company."""
    company_tag: str | None = None
    """The company's tag (``Company.TAGS``), if any."""
    parsed_at: datetime
    evaluation: EvaluationOut
    application_id: int | None = None
    """``applications.id`` when an application was already created for the job."""
    decision: str | None = None
    """``accepted`` / ``rejected`` (``JobDecision``), ``None`` while undecided."""


class EvaluatedJobDetail(EvaluatedJobOut):
    description: str | None
    technologies: list[str] = []
    """Names of the technologies the description names (``JobParseResult.technologies``),
    in extraction order; ``[]`` when none were detected or extraction did not run."""
    evaluation: EvaluationOut | None
    """``None`` when the job is parsed but not yet scored against the latest profile."""


class EvaluatedJobPage(BaseModel):
    items: list[EvaluatedJobOut]
    total: int
    offset: int
    limit: int
    has_more: bool
    candidate_profile_id: int | None
    """Profile the evaluations were made against; ``None`` when no profile exists yet."""


def _latest_profile_id(session: Session) -> int | None:
    return session.scalar(select(func.max(CandidateProfile.id)))


def _decisions(session: Session, parse_result_ids: list[int]) -> dict[int, str]:
    """``{job_parse_result_id: decision}`` for the parse results that have one."""
    if not parse_result_ids:
        return {}
    rows = session.execute(
        select(JobDecision.job_parse_result_id, JobDecision.decision).where(
            JobDecision.job_parse_result_id.in_(parse_result_ids)
        )
    ).all()
    return dict(rows)


def _application_ids(session: Session, parse_result_ids: list[int]) -> dict[int, int]:
    """``{job_parse_result_id: application_id}`` for the parse results that have one."""
    if not parse_result_ids:
        return {}
    rows = session.execute(
        select(Application.job_parse_result_id, Application.id).where(Application.job_parse_result_id.in_(parse_result_ids))
    ).all()
    return dict(rows)


def _evaluated(
    job: Job,
    parsed: JobParseResult,
    evaluation: JobEvaluation | None,
    *,
    threshold: float,
    current_ids: set[int],
    description: bool,
    application_id: int | None = None,
    decision: str | None = None,
) -> dict:
    data = {
        "id": job.id,
        "link": job.link,
        "source": job.source.key,
        "scrape_run_id": job.scrape_run_id,
        "has_html": bool(job.html),
        "title": parsed.title,
        "company": parsed.company.name if parsed.company is not None else None,
        "company_id": parsed.company.id if parsed.company is not None else None,
        "company_tag": parsed.company.tag if parsed.company is not None else None,
        "parsed_at": parsed.parsed_at,
        "evaluation": _evaluation_out(evaluation, threshold, current_ids),
        "application_id": application_id,
        "decision": decision,
    }
    if description:
        data["description"] = parsed.description
        data["technologies"] = [t["name"] for t in parsed.technologies or [] if t.get("name")]
    return data


def _evaluated_query(profile_id: int) -> Select:
    """Every scored job with its *newest* evaluation, whichever profile it was made against.

    A new candidate profile (work history changed) only has scores for the jobs evaluated
    since, so restricting to it would hide every other job until it is re-scored. Taking
    the newest evaluation keeps them listed with their previous score; evaluations against
    ``profile_id`` are always the newest ones where they exist.
    """
    del profile_id  # kept for call-site symmetry; the newest evaluation wins
    newer = aliased(JobEvaluation)
    return (
        select(Job, JobParseResult, JobEvaluation)
        .join(JobParseResult, JobParseResult.job_id == Job.id)
        .join(JobEvaluation, JobEvaluation.job_parse_result_id == JobParseResult.id)
        .where(
            not_(
                select(newer.id)
                .where(
                    newer.job_parse_result_id == JobEvaluation.job_parse_result_id,
                    newer.id > JobEvaluation.id,
                )
                .exists()
            )
        )
        .options(
            joinedload(Job.source),
            joinedload(JobParseResult.company),
            joinedload(JobEvaluation.openrouter_call),
        )
    )


def _items(session: Session, rows, threshold: float) -> list[EvaluatedJobOut]:
    parse_ids = [parsed.id for _, parsed, _ in rows]
    applications = _application_ids(session, parse_ids)
    decisions = _decisions(session, parse_ids)
    current_ids = current_profile_ids(session)
    return [
        EvaluatedJobOut(
            **_evaluated(
                job,
                parsed,
                evaluation,
                threshold=threshold,
                current_ids=current_ids,
                description=False,
                application_id=applications.get(parsed.id),
                decision=decisions.get(parsed.id),
            )
        )
        for job, parsed, evaluation in rows
    ]


def _undecided_relevant(threshold: float) -> ColumnElement[bool]:
    """Relevant, not decided on and without an application: the inbox condition."""
    decided = select(JobDecision.id).where(JobDecision.job_parse_result_id == JobParseResult.id)
    applied = select(Application.id).where(Application.job_parse_result_id == JobParseResult.id)
    return and_(
        JobEvaluation.match_probability >= threshold,
        not_(decided.exists()),
        not_(applied.exists()),
    )


class InboxOut(BaseModel):
    items: list[EvaluatedJobOut]
    count: int
    candidate_profile_id: int | None
    current_profile_ids: list[int] = []
    """Profiles built from the current work history: a score made against any other one is
    outdated. Lets a client refresh the ``outdated`` flag of rows it loaded earlier."""


class FeedPage(BaseModel):
    items: list[EvaluatedJobOut]
    """Newest job first."""
    has_more: bool
    """More (older) rows exist before the last item; only meaningful without ``after``."""
    candidate_profile_id: int | None


INBOX_LIMIT = 500


@router.get("/inbox", response_model=InboxOut)
def jobs_inbox(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> InboxOut:
    """Undecided relevant jobs against the latest profile, best match first."""
    profile_id = _latest_profile_id(session)
    if profile_id is None:
        return InboxOut(items=[], count=0, candidate_profile_id=None)
    query = _evaluated_query(profile_id).where(_undecided_relevant(settings.relevant_job_threshold))
    count = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.execute(
        query.order_by(JobEvaluation.match_probability.desc(), JobEvaluation.id.desc()).limit(INBOX_LIMIT)
    ).all()
    return InboxOut(
        items=_items(session, rows, settings.relevant_job_threshold),
        count=count,
        candidate_profile_id=profile_id,
        current_profile_ids=sorted(current_profile_ids(session)),
    )


@router.get("/feed", response_model=FeedPage)
def jobs_feed(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    before: Annotated[int | None, Query(ge=1)] = None,
    after: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> FeedPage:
    """Every evaluated job not in the inbox, newest job first.

    ``q`` turns the feed into a search: every evaluated job (inbox included) whose title
    or company name contains it (case-insensitive).

    ``before=<job id>`` returns the next older page; ``after=<job id>`` returns newer jobs
    (up to ``limit``, still newest first) for polling. Ordering by job rather than
    evaluation keeps a re-scored job in place.
    """
    profile_id = _latest_profile_id(session)
    if profile_id is None:
        return FeedPage(items=[], has_more=False, candidate_profile_id=None)
    needle = (q or "").strip()
    query = _evaluated_query(profile_id)
    if needle:
        escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        query = query.outerjoin(Company, Company.id == JobParseResult.company_id).where(
            or_(
                JobParseResult.title.ilike(pattern, escape="\\"),
                Company.name.ilike(pattern, escape="\\"),
            )
        )
    else:
        query = query.where(not_(_undecided_relevant(settings.relevant_job_threshold)))
    if before is not None:
        query = query.where(Job.id < before)
    if after is not None:
        query = query.where(Job.id > after)
    rows = session.execute(query.order_by(Job.id.desc()).limit(limit + 1)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    return FeedPage(
        items=_items(session, rows, settings.relevant_job_threshold),
        has_more=has_more,
        candidate_profile_id=profile_id,
    )


# --- manually added jobs --------------------------------------------------------------


class ManualJobIn(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    company: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""
    link: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100_000)] = ""


class ManualJobStatus(BaseModel):
    job_id: int
    status: str
    """``NOT_STARTED`` -> ``COMPLETED`` (or ``FAILED``) of the job's parse run."""
    error: str | None


@router.post("/manual", response_model=ManualJobStatus, status_code=status.HTTP_201_CREATED)
def add_manual_job(
    payload: ManualJobIn,
    session: Annotated[Session, Depends(get_session)],
    queue: Annotated[Queue, Depends(get_queue)],
) -> ManualJobStatus:
    """Store a hand-entered job and enqueue its parse (which then enqueues the evaluation),
    exactly like a freshly scraped job. Poll ``GET /api/jobs/manual/{job_id}``."""
    # Imported here: the scrape package imports app.services.sources, which imports the
    # sources package, so module-level imports would be circular.
    from app.services.sources import sync_sources
    from app.tasks.scrape.scrape import enqueue_parse_jobs
    from app.tasks.scrape.sources import manual

    link = payload.link or f"manual:{uuid.uuid4().hex}"
    if session.scalar(select(Job.id).where(Job.link == link)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "a job with this link already exists")
    source = next((s for s in sync_sources(session) if s.key == "manual"), None)
    if source is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "manual source missing")
    job = Job(
        link=link,
        source=source,
        html=manual.to_html(payload.title, payload.company, payload.description),
    )
    pending = PendingJobParseRun(job=job)
    session.add_all([job, pending])
    session.commit()
    enqueue_parse_jobs(session, [pending], queue)
    return ManualJobStatus(job_id=job.id, status=pending.status, error=pending.error)


@router.get("/manual/{job_id}", response_model=ManualJobStatus)
def manual_job_status(job_id: int, session: Annotated[Session, Depends(get_session)]) -> ManualJobStatus:
    """Parse status of a job (latest parse run)."""
    pending = session.scalar(
        select(PendingJobParseRun).where(PendingJobParseRun.job_id == job_id).order_by(PendingJobParseRun.id.desc()).limit(1)
    )
    if pending is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown job")
    return ManualJobStatus(job_id=job_id, status=pending.status, error=pending.error)


class DecisionIn(BaseModel):
    decision: Literal["accepted", "rejected"]


@router.put("/{job_id}/decision", response_model=EvaluatedJobDetail)
def decide_job(
    job_id: int,
    payload: DecisionIn,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> EvaluatedJobDetail:
    """Record the user's decision about a parsed job (moves it out of the inbox)."""
    parsed = session.scalar(select(JobParseResult).where(JobParseResult.job_id == job_id))
    if parsed is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown or unparsed job")
    set_job_decision(session, parsed.id, payload.decision)
    session.commit()
    return get_job(job_id, session, settings)


class RescoreOut(BaseModel):
    job_id: int
    rq_job_id: str
    """RQ job scoring it; poll ``GET /api/jobs/{job_id}`` until ``outdated`` is false."""


@router.post("/{job_id}/rescore", response_model=RescoreOut, status_code=status.HTTP_202_ACCEPTED)
def rescore_job(
    job_id: int,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    queue: Annotated[Queue, Depends(get_queue)],
) -> RescoreOut:
    """Enqueue scoring a job against the latest candidate profile (the profile is first
    regenerated by the task when the work history changed since it was built).

    404 when the job does not exist or has not been parsed; 409 when its newest score was
    already made against the latest work history; 503 when the queue is unreachable.
    """
    parsed = session.scalar(select(JobParseResult).where(JobParseResult.job_id == job_id))
    if parsed is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown or unparsed job")
    scored_by = session.scalar(
        select(JobEvaluation.candidate_profile_id)
        .where(JobEvaluation.job_parse_result_id == parsed.id)
        .order_by(JobEvaluation.id.desc())
        .limit(1)
    )
    if scored_by is not None and scored_by in current_profile_ids(session):
        raise HTTPException(status.HTTP_409_CONFLICT, "already scored against the latest profile")
    try:
        rq_job = queue.enqueue(
            rescore_parse_results,
            [parsed.id],
            job_id=uuid.uuid4().hex,
            job_timeout=RESCORE_TIMEOUT,
            result_ttl=settings.job_result_ttl,
            failure_ttl=settings.job_result_ttl,
            meta={"job_parse_result_id": parsed.id, "job_id": job_id},
            description=f"re-score job {job_id}",
        )
    except Exception as exc:
        log.exception("Could not enqueue re-scoring of job %d", job_id)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "queue unavailable") from exc
    return RescoreOut(job_id=job_id, rq_job_id=rq_job.id)


@router.get("", response_model=EvaluatedJobPage)
def list_jobs(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
    source: str | None = None,
    min_probability: Annotated[float | None, Query(ge=0, le=1)] = None,
    sort: SortOrder = "newest",
) -> EvaluatedJobPage:
    """Page of jobs evaluated against the latest candidate profile.

    ``sort=newest`` (default) lists the most recently evaluated first; ``sort=match`` lists
    the best matches first. ``min_probability`` keeps only jobs scored at or above it.
    """
    profile_id = _latest_profile_id(session)
    if profile_id is None:
        return EvaluatedJobPage(
            items=[],
            total=0,
            offset=offset,
            limit=limit,
            has_more=False,
            candidate_profile_id=None,
        )

    query = _evaluated_query(profile_id)
    if source:
        query = query.join(Job.source).where(ScrapeSource.key == source)
    if min_probability is not None:
        query = query.where(JobEvaluation.match_probability >= min_probability)

    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    if sort == "match":
        query = query.order_by(JobEvaluation.match_probability.desc(), JobEvaluation.id.desc())
    else:
        query = query.order_by(JobEvaluation.id.desc())
    rows = session.execute(query.offset(offset).limit(limit)).all()
    items = _items(session, rows, settings.relevant_job_threshold)
    return EvaluatedJobPage(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + len(items) < total,
        candidate_profile_id=profile_id,
    )


@router.get("/{job_id}", response_model=EvaluatedJobDetail)
def get_job(
    job_id: int,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> EvaluatedJobDetail:
    """A single parsed job with its full description and its score against the latest
    candidate profile (``evaluation`` is ``null`` when it has not been scored yet).

    404 when the job does not exist or has not been parsed.
    """
    row = session.execute(
        select(Job, JobParseResult)
        .join(JobParseResult, JobParseResult.job_id == Job.id)
        .where(Job.id == job_id)
        .options(joinedload(JobParseResult.company))
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown or unparsed job")
    job, parsed = row

    # Newest score from any profile (see ``_evaluated_query``).
    evaluation = newest_evaluations(session, [parsed.id]).get(parsed.id)
    application_id = _application_ids(session, [parsed.id]).get(parsed.id)
    return EvaluatedJobDetail(
        **_evaluated(
            job,
            parsed,
            evaluation,
            threshold=settings.relevant_job_threshold,
            current_ids=current_profile_ids(session),
            description=True,
            application_id=application_id,
            decision=_decisions(session, [parsed.id]).get(parsed.id),
        )
    )
