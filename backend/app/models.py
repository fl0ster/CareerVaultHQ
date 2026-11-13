"""Database models."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String, Text
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
    company: Mapped[str | None] = mapped_column(String(256))
    """Hiring company as returned by the source's ``parse_company``."""
    description: Mapped[str | None] = mapped_column(Text)
    """Plain-text job description as returned by the source's ``parse_description``."""
    parsed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    job: Mapped[Job] = relationship()


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
