"""Database models."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class ScrapeRun(Base):
    """One execution of the scrape task (all sources or a single one)."""

    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rq_job_id: Mapped[str | None] = mapped_column(String(64), index=True)
    source: Mapped[str | None] = mapped_column(String(64))
    """Source name the run was limited to; ``None`` means every source."""
    status: Mapped[str] = mapped_column(String(16), default="running")
    """``running`` -> ``finished`` (some sources may still have failed) or ``failed``."""
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scraped_count: Mapped[int] = mapped_column(Integer, default=0)
    """Total listings returned by the scrapers."""
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    """Listings not seen before and inserted into ``jobs``."""
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    """Listings whose link was already in ``jobs``."""
    failed_sources: Mapped[str | None] = mapped_column(Text)
    """Comma separated names of sources that raised."""
    error: Mapped[str | None] = mapped_column(Text)

    jobs: Mapped[list[Job]] = relationship(back_populates="scrape_run")


class Job(Base):
    """A scraped job listing. ``link`` identifies the job across runs."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    link: Mapped[str] = mapped_column(String(2048), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(64), index=True)
    html: Mapped[str | None] = mapped_column(Text)
    """Raw HTML of the job page as fetched during scraping (``None`` if unavailable)."""
    scrape_run_id: Mapped[int] = mapped_column(
        ForeignKey("scrape_runs.id", ondelete="SET NULL"), index=True, nullable=True
    )
    """Run that first discovered this job (its ``started_at`` is when the job was scraped)."""

    scrape_run: Mapped[ScrapeRun | None] = relationship(back_populates="jobs")


class PendingJobParseRun(Base):
    """A request to parse one scraped ``Job``. Created by the scrape task right after the
    job is inserted; the parse task flips ``status`` and records ``parsed_at``."""

    __tablename__ = "pending_job_parse_runs"

    STATUS_NOT_STARTED = "NOT_STARTED"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_FAILED = "FAILED"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    rq_job_id: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default=STATUS_NOT_STARTED, index=True)
    """``NOT_STARTED`` -> ``COMPLETED`` (or ``FAILED`` when the parser raised)."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """When the parse task finished (``None`` while ``NOT_STARTED``)."""
    error: Mapped[str | None] = mapped_column(Text)

    job: Mapped[Job] = relationship()


class JobParseResult(Base):
    """Structured data extracted from a ``Job``'s raw HTML. One row per job; re-parsing
    overwrites it."""

    __tablename__ = "job_parse_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(512))
    """Job title as returned by the source's ``parse_title``."""
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    """Canonical ``Company`` the source's ``parse_company`` value was resolved to by
    ``app.services.companies.resolve_company`` (``None`` when the page named no company)."""
    description: Mapped[str | None] = mapped_column(Text)
    """Plain-text job description as returned by the source's ``parse_description``."""
    parsed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    job: Mapped[Job] = relationship()
    company: Mapped[Company | None] = relationship(back_populates="parse_results")


class Company(Base):
    """The canonical record of a hiring company. Every spelling seen in a job listing is
    mapped to exactly one of these rows through ``CompanyAlias``; ``job_parse_results``
    reference the canonical row, never the raw text from the page."""

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    """Official, clean display name (the first spelling seen until edited by hand)."""
    normalized_name: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    """``app.services.companies.normalize_company_name(name)``; the deterministic lookup key
    and the string fuzzy matching compares against."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    aliases: Mapped[list[CompanyAlias]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    parse_results: Mapped[list[JobParseResult]] = relationship(back_populates="company")


class CompanyAlias(Base):
    """One spelling of a company name (variation, typo, legal-form suffix, previous name)
    and the canonical ``Company`` it maps to. Looked up by ``normalized_alias`` before any
    fuzzy matching happens, so a spelling is resolved the same way every time."""

    __tablename__ = "company_aliases"

    MATCH_EXACT = "exact"
    """The normalized spelling equalled the canonical ``normalized_name``."""
    MATCH_FUZZY = "fuzzy"
    """Attached by similarity to an existing company (see ``similarity``)."""
    MATCH_NEW = "new"
    """First spelling ever seen; it created the canonical row."""
    MATCH_MANUAL = "manual"
    """Entered or re-pointed by a human."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    alias: Mapped[str] = mapped_column(String(256), nullable=False)
    """The spelling exactly as it appeared on the job page."""
    normalized_alias: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    """``normalize_company_name(alias)``; unique so one spelling maps to one company."""
    match_kind: Mapped[str] = mapped_column(String(16), default=MATCH_NEW)
    """How the alias was attached: ``exact``, ``fuzzy``, ``new`` or ``manual``."""
    similarity: Mapped[float | None] = mapped_column(Float)
    """Score (0-1) of the fuzzy match that attached it (``None`` otherwise)."""
    source: Mapped[str | None] = mapped_column(String(64))
    """Scrape source the spelling was first seen on."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    company: Mapped[Company] = relationship(back_populates="aliases")


class WorkHistoryEntry(Base):
    """One position in the user's work history (employer, role, dates, tech stack)."""

    __tablename__ = "work_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date_start: Mapped[date] = mapped_column(Date, index=True)
    date_end: Mapped[date | None] = mapped_column(Date)
    """``None`` means the position is current."""
    employer: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(256))
    location: Mapped[str | None] = mapped_column(String(256))
    tech: Mapped[list[str]] = mapped_column(JSON, default=list)
    """Technologies used in the role, stored as a JSON array of strings."""
    context: Mapped[str | None] = mapped_column(Text)
    """Free-form, potentially long description of the role."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CandidateProfile(Base):
    """Free-text description of the candidate. Several rows may exist; only the most
    recently created one (highest ``id``) is considered current."""

    __tablename__ = "candidate_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content: Mapped[str] = mapped_column(Text, default="")
    work_history_id: Mapped[str | None] = mapped_column(String(256))
    """Opaque reference to the work history this profile was built from (free string for now)."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class OpenRouterCall(Base):
    """One request made to OpenRouter through ``app.services.openrouter``. Every call is
    recorded, including failed ones, so spend and prompts can be audited."""

    __tablename__ = "openrouter_calls"

    KIND_CHAT = "chat"
    KIND_DECISION = "decision"
    STATUS_OK = "ok"
    STATUS_FAILED = "failed"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(128), index=True)
    """Who made the call, e.g. ``api.openrouter.chat`` or ``tasks.parse``."""
    kind: Mapped[str] = mapped_column(String(16), index=True)
    """``chat`` (free text) or ``decision`` (structured JSON)."""
    model: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(16), default=STATUS_OK, index=True)
    input: Mapped[dict] = mapped_column(JSON)
    """Request body sent to OpenRouter (messages, response_format, ...)."""
    output: Mapped[dict | None] = mapped_column(JSON)
    """Raw response body returned by OpenRouter (``None`` when the request failed)."""
    cost: Mapped[float | None] = mapped_column(Float)
    """Cost in USD as reported in ``usage.cost`` by the API."""
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    generation_id: Mapped[str | None] = mapped_column(String(128))
    """OpenRouter's ``id`` for the completion."""
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JobEvaluation(Base):
    """How well a parsed job (``job_parse_results``) matches a ``CandidateProfile``, as
    judged by the OpenRouter decisions API (``app.tasks.evaluate``). One row per
    (parsed job, profile) pair; a newer profile yields a fresh row for every job."""

    __tablename__ = "job_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "job_parse_result_id", "candidate_profile_id", name="uq_job_evaluation_pair"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_parse_result_id: Mapped[int] = mapped_column(
        ForeignKey("job_parse_results.id", ondelete="CASCADE"), index=True, nullable=False
    )
    candidate_profile_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    match_probability: Mapped[float] = mapped_column(Float, nullable=False)
    """Probability (0-1) that the job is a good match, from the ``noul`` answer."""
    openrouter_call_id: Mapped[int | None] = mapped_column(
        ForeignKey("openrouter_calls.id", ondelete="SET NULL"), index=True
    )
    """The ``openrouter_calls`` row that produced the score (prompt, cost, raw answer, model)."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job_parse_result: Mapped[JobParseResult] = relationship()
    candidate_profile: Mapped[CandidateProfile] = relationship()
    openrouter_call: Mapped[OpenRouterCall | None] = relationship()


class JobEvaluationFailure(Base):
    """Bookkeeping for a (parsed job, profile) pair whose OpenRouter call failed, so the
    evaluation is retried with a backoff instead of on every run. One row per pair; it is
    deleted once the pair is scored successfully (see ``app.tasks.evaluate``)."""

    __tablename__ = "job_evaluation_failures"
    __table_args__ = (
        UniqueConstraint(
            "job_parse_result_id", "candidate_profile_id", name="uq_job_evaluation_failure_pair"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_parse_result_id: Mapped[int] = mapped_column(
        ForeignKey("job_parse_results.id", ondelete="CASCADE"), index=True, nullable=False
    )
    candidate_profile_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    """How many times the pair has failed so far."""
    last_error: Mapped[str | None] = mapped_column(Text)
    last_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    """The pair is not selected for evaluation before this time."""


class CandidateDetails(Base):
    """Personal details printed on a generated CV (name, contact lines, education,
    certifications, languages and the consent clause). A singleton: at most one row exists
    and ``PUT /api/candidate-details`` upserts it."""

    __tablename__ = "candidate_details"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    first_name: Mapped[str] = mapped_column(String(128), default="")
    last_name: Mapped[str] = mapped_column(String(128), default="")
    email: Mapped[str] = mapped_column(String(256), default="")
    phone: Mapped[str] = mapped_column(String(64), default="")
    website: Mapped[str] = mapped_column(String(512), default="")
    github: Mapped[str] = mapped_column(String(512), default="")
    linkedin: Mapped[str] = mapped_column(String(512), default="")
    location: Mapped[str] = mapped_column(String(256), default="")
    education: Mapped[list[dict]] = mapped_column(JSON, default=list)
    """``[{"degree", "institution", "date_start", "date_end", "note"}, ...]``; dates are free
    text (``Oct 2012``) because they are printed verbatim."""
    certifications: Mapped[list[str]] = mapped_column(JSON, default=list)
    languages: Mapped[list[dict]] = mapped_column(JSON, default=list)
    """``[{"language": "English", "level": "Advanced (C1)"}, ...]``."""
    consent_text: Mapped[str] = mapped_column(Text, default="")
    """Data-processing consent printed in small type at the end of the CV; blank = omitted."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class GeneratedCV(Base):
    """A CV tailored to one parsed job by ``app.tasks.cv.generate_cv``. The row is created
    (``queued``) when the generation is requested and updated by the task as it runs; the
    ``.tex`` and ``.pdf`` land under ``settings.cv_root / <id>``."""

    __tablename__ = "generated_cvs"

    STATUS_QUEUED = "queued"
    STATUS_RUNNING = "running"
    STATUS_FINISHED = "finished"
    STATUS_FAILED = "failed"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_parse_result_id: Mapped[int] = mapped_column(
        ForeignKey("job_parse_results.id", ondelete="CASCADE"), index=True, nullable=False
    )
    rq_job_id: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default=STATUS_QUEUED, index=True)
    """``queued`` -> ``running`` -> ``finished`` or ``failed``."""
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    headline_role: Mapped[str | None] = mapped_column(String(256))
    """Job title printed under the candidate's name."""
    core_technologies: Mapped[list[str]] = mapped_column(JSON, default=list)
    """The one or two technologies printed next to the headline role."""
    summary: Mapped[str | None] = mapped_column(Text)
    """Professional summary that opens the CV."""
    tex_path: Mapped[str | None] = mapped_column(String(1024))
    pdf_path: Mapped[str | None] = mapped_column(String(1024))
    pipeline: Mapped[dict | None] = mapped_column(JSON)
    """What the pipeline did: relevance per role, which roles were listed or condensed,
    the timeline log and any warnings (steps that fell back to the original text)."""

    job_parse_result: Mapped[JobParseResult] = relationship()
