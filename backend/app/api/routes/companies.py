"""Canonical companies resolved from scraped job listings (see ``app.services.companies``).

``GET /api/companies?offset=0&limit=50&q=tech`` returns a page of companies, alphabetically,
with how many parsed jobs reference each one. ``GET /api/companies/{id}?jobs_limit=10`` adds
the aliases (every spelling that was mapped to the company) and its latest parsed jobs.
``PATCH /api/companies/{id}`` with ``{"notes": "..."}`` and/or ``{"tag": "favourite" | null}``
updates the company's notes / tag (``GET /api/companies/tags`` lists the allowed tags).
``GET /api/companies/application-stats`` counts each company's applications by outcome.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import (
    Application,
    ApplicationEvent,
    ApplicationStatus,
    Company,
    CompanyAlias,
    Job,
    JobParseResult,
    ScrapeSource,
)
from app.services.companies import normalize_company_name

router = APIRouter()

MAX_PAGE_SIZE = 200
MAX_COMPANY_JOBS = 100


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    normalized_name: str
    notes: str = ""
    tag: str | None = None
    """One of ``Company.TAGS`` or ``None``."""
    created_at: datetime
    updated_at: datetime
    job_count: int = 0
    """Parsed jobs (``job_parse_results``) pointing at this company."""


class CompanyAliasOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    alias: str
    normalized_alias: str
    match_kind: str
    similarity: float | None = None
    source: str | None = None
    """Key of the scrape source the spelling was first seen on."""
    created_at: datetime

    @field_validator("source", mode="before")
    @classmethod
    def _source_key(cls, value: object) -> object:
        return value.key if isinstance(value, ScrapeSource) else value


class CompanyJobOut(BaseModel):
    """A parsed job of the company, newest parse first."""

    job_id: int
    parse_result_id: int
    link: str
    source: str
    title: str | None = None
    parsed_at: datetime


class CompanyFull(CompanyOut):
    aliases: list[CompanyAliasOut]
    jobs: list[CompanyJobOut]
    """Up to ``jobs_limit`` parsed jobs, most recently parsed first (``job_count`` has the
    total)."""


class CompanyPage(BaseModel):
    items: list[CompanyOut]
    total: int
    offset: int
    limit: int
    has_more: bool


class CompanyUpdate(BaseModel):
    """Only the fields present in the body are changed; ``"tag": null`` clears the tag."""

    notes: str | None = None
    tag: str | None = None

    @field_validator("tag")
    @classmethod
    def _known_tag(cls, value: str | None) -> str | None:
        if value is not None and value not in Company.TAGS:
            raise ValueError(f"must be one of {', '.join(Company.TAGS)} or null")
        return value

    @model_validator(mode="after")
    def _something_to_update(self) -> CompanyUpdate:
        if not self.model_fields_set & {"notes", "tag"}:
            raise ValueError("nothing to update: send notes and/or tag")
        if "notes" in self.model_fields_set and self.notes is None:
            raise ValueError("notes cannot be null")
        return self


def _job_count_subquery():
    return (
        select(JobParseResult.company_id, func.count().label("job_count"))
        .group_by(JobParseResult.company_id)
        .subquery()
    )


def _to_out(company: Company, job_count: int | None) -> CompanyOut:
    out = CompanyOut.model_validate(company)
    out.job_count = job_count or 0
    out.notes = company.notes or ""
    return out


def _job_count(session: Session, company_id: int) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(JobParseResult)
            .where(JobParseResult.company_id == company_id)
        )
        or 0
    )


@router.get("", response_model=CompanyPage)
def list_companies(
    session: Annotated[Session, Depends(get_session)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
    q: str | None = None,
) -> CompanyPage:
    """Page of companies, alphabetically by name. ``q`` filters by substring of the
    normalised name or any alias."""
    counts = _job_count_subquery()
    query = select(Company, counts.c.job_count).outerjoin(counts, counts.c.company_id == Company.id)
    count_query = select(func.count()).select_from(Company)
    if q:
        needle = f"%{normalize_company_name(q)}%"
        matching_alias = select(CompanyAlias.company_id).where(
            CompanyAlias.normalized_alias.like(needle)
        )
        condition = Company.normalized_name.like(needle) | Company.id.in_(matching_alias)
        query = query.where(condition)
        count_query = count_query.where(condition)

    total = session.scalar(count_query) or 0
    rows = session.execute(
        query.order_by(Company.name, Company.id).offset(offset).limit(limit)
    ).all()
    return CompanyPage(
        items=[_to_out(company, job_count) for company, job_count in rows],
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + len(rows) < total,
    )


@router.get("/tags", response_model=list[str])
def list_company_tags() -> list[str]:
    """The tags a company can have, in display order."""
    return list(Company.TAGS)


APPLICATION_OUTCOMES = ("APPLIED", "INTERVIEW", "REJECTED", "OFFER")
"""Buckets of ``GET /application-stats``, from least to most decisive."""


def _outcome(keys: set[str]) -> str | None:
    """The bucket of an application that went through the states ``keys``: ``OFFER`` if it
    got one, else ``REJECTED`` if rejected, else ``INTERVIEW`` if interviewed, else
    ``APPLIED`` if applied; ``None`` (not counted) otherwise, e.g. only shortlisted."""
    for key in reversed(APPLICATION_OUTCOMES):
        if key in keys:
            return key
    return None


@router.get("/application-stats", response_model=dict[int, dict[str, int]])
def application_stats(session: Annotated[Session, Depends(get_session)]) -> dict[int, dict[str, int]]:
    """``{company_id: {outcome: count}}`` over every application to a resolved company,
    each counted once in its most decisive outcome (see ``_outcome``). Zero counts and
    companies without counted applications are left out."""
    rows = session.execute(
        select(JobParseResult.company_id, Application.id, ApplicationStatus.key)
        .join(Application, Application.job_parse_result_id == JobParseResult.id)
        .join(ApplicationEvent, ApplicationEvent.application_id == Application.id)
        .join(ApplicationStatus, ApplicationStatus.id == ApplicationEvent.status_id)
        .where(JobParseResult.company_id.is_not(None), ApplicationEvent.planned.is_(False))
    ).all()
    states: dict[tuple[int, int], set[str]] = {}
    for company_id, application_id, key in rows:
        states.setdefault((company_id, application_id), set()).add(key)
    stats: dict[int, dict[str, int]] = {}
    for (company_id, _), keys in states.items():
        outcome = _outcome(keys)
        if outcome is not None:
            counts = stats.setdefault(company_id, {})
            counts[outcome] = counts.get(outcome, 0) + 1
    return stats


@router.get("/{company_id}", response_model=CompanyFull)
def get_company(
    company_id: int,
    session: Annotated[Session, Depends(get_session)],
    jobs_limit: Annotated[int, Query(ge=0, le=MAX_COMPANY_JOBS)] = 10,
) -> CompanyFull:
    """A single company with every alias mapped to it and its ``jobs_limit`` latest jobs."""
    company = session.get(Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown company")
    job_count = _job_count(session, company.id)
    latest = session.execute(
        select(JobParseResult, Job)
        .join(Job, Job.id == JobParseResult.job_id)
        .where(JobParseResult.company_id == company.id)
        .order_by(JobParseResult.parsed_at.desc(), JobParseResult.id.desc())
        .limit(jobs_limit)
    ).all()
    return CompanyFull(
        **_to_out(company, job_count).model_dump(),
        aliases=[CompanyAliasOut.model_validate(alias) for alias in company.aliases],
        jobs=[
            CompanyJobOut(
                job_id=job.id,
                parse_result_id=parsed.id,
                link=job.link,
                source=job.source.key,
                title=parsed.title,
                parsed_at=parsed.parsed_at,
            )
            for parsed, job in latest
        ],
    )


@router.patch("/{company_id}", response_model=CompanyOut)
def update_company(
    company_id: int,
    payload: CompanyUpdate,
    session: Annotated[Session, Depends(get_session)],
) -> CompanyOut:
    """Change the company's notes and/or tag."""
    company = session.get(Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown company")
    if "notes" in payload.model_fields_set:
        company.notes = payload.notes
    if "tag" in payload.model_fields_set:
        company.tag = payload.tag
    session.commit()
    return _to_out(company, _job_count(session, company.id))
