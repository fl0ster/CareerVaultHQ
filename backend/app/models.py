"""Database models."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
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


class ScrapeSource(Base):
    """One row per scraper plugin module in ``app.tasks.scrape.sources``; ``key`` is the
    module name. Rows are created and refreshed by ``app.services.sources.sync_sources``
    and never deleted (``jobs`` reference them): a module that disappears from disk is kept
    with ``module_error`` set. ``enabled`` and ``scrape_interval_seconds`` are edited through ``PATCH /api/sources/{key}``; the ``last_*`` fields are maintained by the
    scrape task and ``next_scrape_at`` by ``app.scheduler``."""

    __tablename__ = "scrape_sources"

    HEALTH_UNKNOWN = "unknown"
    """Never run yet."""
    HEALTH_HEALTHY = "healthy"
    """Last run succeeded and returned listings."""
    HEALTH_DEGRADED = "degraded"
    """Failed recently, or succeeded with zero listings (markup probably changed)."""
    HEALTH_FAILING = "failing"
    """``FAILING_AFTER`` or more failures in a row."""
    HEALTH_BROKEN = "broken"
    """The module cannot be imported, violates the contract or was removed."""

    FAILING_AFTER = 3
    """Consecutive failures at which ``health`` turns ``failing``."""

    MODULE_MISSING = "module not found"
    """``module_error`` for a row whose module is no longer in the sources package."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    """Module name in ``app.tasks.scrape.sources``."""
    name: Mapped[str] = mapped_column(String(128))
    """The module's ``NAME``."""
    url: Mapped[str | None] = mapped_column(String(2048))
    """The module's ``URL`` (listing page)."""
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    """``False`` excludes the source from "scrape all"; it can still be run by name."""
    module_error: Mapped[str | None] = mapped_column(Text)
    """Import/contract problem reported by discovery (``None`` when the module is usable)."""
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    """Error of the last run (``None`` when it succeeded)."""
    last_scraped_count: Mapped[int | None] = mapped_column(Integer)
    """Listings returned by the last run."""
    last_new_count: Mapped[int | None] = mapped_column(Integer)
    """Listings inserted into ``jobs`` by the last run."""
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    scrape_interval_seconds: Mapped[int | None] = mapped_column(Integer)
    """How often the scheduler scrapes the source; ``None`` uses
    ``Settings.scrape_interval_seconds``."""
    next_scrape_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """When the scheduler enqueues the next run (jitter included). ``None`` means "not
    planned yet": the scheduler computes it on its next tick."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    jobs: Mapped[list[Job]] = relationship(back_populates="source")

    @property
    def health(self) -> str:
        """Derived from the run bookkeeping; one of the ``HEALTH_*`` constants."""
        if self.module_error is not None:
            return self.HEALTH_BROKEN
        if self.last_run_at is None:
            return self.HEALTH_UNKNOWN
        if self.consecutive_failures >= self.FAILING_AFTER:
            return self.HEALTH_FAILING
        if self.consecutive_failures >= 1 or self.last_scraped_count == 0:
            return self.HEALTH_DEGRADED
        return self.HEALTH_HEALTHY


class ScrapeRun(Base):
    """One execution of the scrape task (all sources or a single one)."""

    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rq_job_id: Mapped[str | None] = mapped_column(String(64), index=True)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("scrape_sources.id", ondelete="SET NULL"), index=True
    )
    """Source the run was limited to; ``None`` means every enabled source."""
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

    source: Mapped[ScrapeSource | None] = relationship()
    jobs: Mapped[list[Job]] = relationship(back_populates="scrape_run")


class Job(Base):
    """A scraped job listing. ``link`` identifies the job across runs."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    link: Mapped[str] = mapped_column(String(2048), unique=True, index=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("scrape_sources.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    """The ``ScrapeSource`` (plugin module) that found the job and parses its page."""
    html: Mapped[str | None] = mapped_column(Text)
    """Raw HTML of the job page as fetched during scraping (``None`` if unavailable)."""
    scrape_run_id: Mapped[int] = mapped_column(
        ForeignKey("scrape_runs.id", ondelete="SET NULL"), index=True, nullable=True
    )
    """Run that first discovered this job (its ``started_at`` is when the job was scraped)."""

    source: Mapped[ScrapeSource] = relationship(back_populates="jobs")
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

    TAGS = ("favourite", "interested", "avoid")
    """Allowed values of ``tag``, in the order the UI cycles through them."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    """Official, clean display name (the first spelling seen until edited by hand)."""
    normalized_name: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    """``app.services.companies.normalize_company_name(name)``; the deterministic lookup key
    and the string fuzzy matching compares against."""
    notes: Mapped[str] = mapped_column(Text, default="")
    """Free-text notes about the company, edited by hand (also from its applications)."""
    tag: Mapped[str | None] = mapped_column(String(32))
    """One of ``TAGS`` set by hand, or ``None``; shown next to the company's jobs too."""
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
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("scrape_sources.id", ondelete="SET NULL"), index=True
    )
    """Scrape source the spelling was first seen on (``None`` for manual entries)."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    company: Mapped[Company] = relationship(back_populates="aliases")
    source: Mapped[ScrapeSource | None] = relationship()


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


class JobDecision(Base):
    """What the user decided about a parsed job on the Jobs tab: ``accepted`` (an
    application was created for it) or ``rejected`` (dismissed, shown crossed out). One row
    per parsed job, so the decision survives re-evaluation against a newer profile. Relevant
    jobs without a decision (and without an application) form the Jobs tab inbox."""

    __tablename__ = "job_decisions"

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DECISIONS = (ACCEPTED, REJECTED)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_parse_result_id: Mapped[int] = mapped_column(
        ForeignKey("job_parse_results.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


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


class ApplicationStatus(Base):
    """A state an ``Application`` can be in (``APPLIED``, ``INTERVIEW``, ...). Kept in a
    table rather than an enum so new states can be added without a schema change; the
    defaults in ``DEFAULTS`` are created by ``app.services.applications.ensure_statuses``."""

    __tablename__ = "application_statuses"

    DEFAULTS: tuple[tuple[str, str, str], ...] = (
        ("SHORTLISTED", "Shortlisted", "APPLIED"),
        ("APPLIED", "Applied", "INTERVIEW"),
        ("INTERVIEW", "Interview", "INTERVIEW"),
        ("OFFER", "Offer", ""),
        ("REJECTED", "Rejected", ""),
    )
    """``(key, label, next_key)`` triples created on first use, in display order; an empty
    ``next_key`` means the state has no default successor."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    """Stable identifier used by the API, upper case (``APPLIED``)."""
    label: Mapped[str] = mapped_column(String(128))
    position: Mapped[int] = mapped_column(Integer, default=0)
    """Display order; lower first."""
    next_key: Mapped[str | None] = mapped_column(String(64))
    """``key`` of the state an application usually moves to from this one (one click in
    the UI); ``None`` when there is no default next state."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Application(Base):
    """A job application made for an evaluated job. One per parsed job (re-evaluating the
    job against a newer profile does not allow a second one). Its current state is the most
    recent ``ApplicationEvent``; ``notes`` is free text about the application as a whole."""

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_parse_result_id: Mapped[int] = mapped_column(
        ForeignKey("job_parse_results.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    job_evaluation_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_evaluations.id", ondelete="SET NULL"), index=True
    )
    """The evaluation the application was created from (``None`` once it is deleted)."""
    generated_cv_id: Mapped[int | None] = mapped_column(
        ForeignKey("generated_cvs.id", ondelete="SET NULL"), index=True
    )
    """The CV generated for this application (the latest one when regenerated)."""
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    job_parse_result: Mapped[JobParseResult] = relationship()
    job_evaluation: Mapped[JobEvaluation | None] = relationship()
    generated_cv: Mapped[GeneratedCV | None] = relationship()
    events: Mapped[list[ApplicationEvent]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="(ApplicationEvent.occurred_at, ApplicationEvent.id)",
    )

    @property
    def history(self) -> list[ApplicationEvent]:
        """States the application actually went through, oldest first (planned rounds left out)."""
        return [e for e in self.events if not e.planned]

    @property
    def plan(self) -> list[ApplicationEvent]:
        """Planned interview rounds not held yet, in round order."""
        return sorted((e for e in self.events if e.planned), key=lambda e: e.id)

    @property
    def current_event(self) -> ApplicationEvent | None:
        """The latest state change (planned rounds do not count)."""
        return next((e for e in reversed(self.events) if not e.planned), None)


class ApplicationEvent(Base):
    """One state the application went through (applied on X, interview on Y, ...), with a
    note of its own, or, with ``planned``, an interview round that is expected but not held
    yet (always ``INTERVIEW``). Recording an interview fills the first planned round."""

    __tablename__ = "application_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True, nullable=False
    )
    status_id: Mapped[int] = mapped_column(
        ForeignKey("application_statuses.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    note: Mapped[str] = mapped_column(Text, default="")
    planned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    """A planned interview round that has not happened yet."""
    title: Mapped[str] = mapped_column(String(128), default="")
    """Kind of interview round ("Culture match", "Technical", ...)."""
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow)
    """When the state was reached (defaults to when it was recorded; editable). For a planned
    round the optional scheduled time; always set on held events."""
    source: Mapped[str] = mapped_column(String(16), default="manual", server_default="manual")
    """Who recorded the state: ``SOURCE_MANUAL`` (the user) or ``SOURCE_GMAIL`` (the Gmail
    rejection monitor, shown with a lightning bolt in the UI)."""
    source_ref: Mapped[str | None] = mapped_column(String(128))
    """Reference to what triggered an automatic event (the Gmail message id)."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    SOURCE_MANUAL = "manual"
    SOURCE_GMAIL = "gmail"

    application: Mapped[Application] = relationship(back_populates="events")
    status: Mapped[ApplicationStatus] = relationship()


class GmailMonitorSettings(Base):
    """Configuration and run state of the Gmail rejection monitor. A single row (``id`` 1),
    created on first use by ``app.services.gmail_monitor.get_monitor_settings``.

    The monitored mailbox is reached through a Google Apps Script web app the user deploys
    in that account (``script_url``); every request carries ``secret``."""

    __tablename__ = "gmail_monitor_settings"

    DEFAULT_LABEL = "rejection-registered"
    DEFAULT_INTERVAL_SECONDS = 30 * 60
    DEFAULT_LOOKBACK_DAYS = 7
    DEFAULT_THRESHOLD = 0.9

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    email: Mapped[str] = mapped_column(String(320), default="")
    """Address of the monitored account; the script must report the same one."""
    script_url: Mapped[str] = mapped_column(String(1024), default="")
    """``https://script.google.com/macros/s/.../exec`` of the deployed web app."""
    secret: Mapped[str] = mapped_column(String(128), nullable=False)
    """Shared token embedded in the script and sent with every request."""
    label: Mapped[str] = mapped_column(String(128), default=DEFAULT_LABEL)
    """Gmail label added to the mails whose rejection was registered."""
    interval_seconds: Mapped[int] = mapped_column(Integer, default=DEFAULT_INTERVAL_SECONDS)
    lookback_days: Mapped[int] = mapped_column(Integer, default=DEFAULT_LOOKBACK_DAYS)
    """Only unread mails received within this many days are checked."""
    threshold: Mapped[float] = mapped_column(Float, default=DEFAULT_THRESHOLD)
    """Minimum probability (0-1) that a mail is a rejection before it is acted on."""
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """When the scheduler runs the check next; ``None`` means as soon as possible."""
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(16))
    """``ok`` or ``failed``."""
    last_error: Mapped[str | None] = mapped_column(Text)
    last_summary: Mapped[dict | None] = mapped_column(JSON)
    """Counts of the last run: ``{"checked": n, "applied": n, ...}``."""
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class GmailProcessedMail(Base):
    """A mail the Gmail rejection monitor looked at, whatever the outcome, so it is never
    sent to OpenRouter twice. Only ``OUTCOME_APPLIED`` mails are marked read and labelled;
    the others are left untouched in the inbox."""

    __tablename__ = "gmail_processed_mails"

    OUTCOME_APPLIED = "applied"
    """Rejection registered on ``application_id``; the mail was marked read and labelled."""
    OUTCOME_NOT_REJECTION = "not_rejection"
    """Not a rejection with enough confidence."""
    OUTCOME_EXTRACTION_FAILED = "extraction_failed"
    """Company could not be read from the mail."""
    OUTCOME_NO_MATCH = "no_match"
    """No open application matches the company (and role)."""
    OUTCOME_AMBIGUOUS = "ambiguous"
    """Several open applications match and the role does not single one out."""
    OUTCOME_MARK_FAILED = "mark_failed"
    """Rejection registered, but the mail could not be marked read / labelled."""
    OUTCOME_ERROR = "error"
    """Processing failed unexpectedly (see ``error``)."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    thread_id: Mapped[str | None] = mapped_column(String(128))
    subject: Mapped[str] = mapped_column(String(1024), default="")
    sender: Mapped[str] = mapped_column(String(512), default="")
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(32), index=True)
    probability: Mapped[float | None] = mapped_column(Float)
    """Probability that the mail is a rejection (Jev ``is_rejection``)."""
    company: Mapped[str | None] = mapped_column(String(512))
    role: Mapped[str | None] = mapped_column(String(512))
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"), index=True
    )
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
