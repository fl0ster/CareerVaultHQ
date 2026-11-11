"""Database models."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, Text
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
