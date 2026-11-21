"""OpenRouter: free-text chat (``POST /chat``), Jev decisions (``POST /decide``) and
spend aggregates for the Cost page (``GET /cost``), read from the hourly
``openrouter_usage`` rollup that ``app.services.openrouter`` maintains.

Other routes/tasks should not go through HTTP; they use ``OpenRouterService`` directly.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import OpenRouterUsage
from app.services.openrouter import (
    OpenRouterError,
    OpenRouterNotConfigured,
    OpenRouterService,
    Usage,
    get_openrouter,
)

router = APIRouter()

SOURCE_CHAT = "api.openrouter.chat"
SOURCE_DECIDE = "api.openrouter.decide"


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str


class UsageOut(BaseModel):
    cost: float | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None


class _RequestBase(BaseModel):
    prompt: str | None = None
    """Single user message; ignored when ``messages`` is given."""
    system: str | None = None
    messages: list[ChatMessage] | None = None
    model: str | None = None
    """Overrides the default model from settings."""
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1)
    source: str | None = Field(default=None, max_length=128)
    """Optional label stored with the call; defaults to the route name."""


class ChatRequest(_RequestBase):
    pass


class ChatResponse(BaseModel):
    model: str
    text: str
    usage: UsageOut


class DecideRequest(BaseModel):
    """Jev Decisions API request (https://openrouter.ai/docs/guides/community/jev)."""

    state: str | dict[str, Any] | list[Any]
    """Content to judge, e.g. ``{"candidate_profile": ..., "job_description": ...}``."""
    questions: dict[str, dict[str, Any]] = Field(min_length=1)
    """Name -> question, e.g. ``{"type": "noul", "instructions": ..., "criteria": {...}}``."""
    model: str | None = None
    """Overrides ``OPENROUTER_DECISION_MODEL``."""
    extra: dict[str, Any] | None = None
    """Merged into the request body (``assets``, ``provider``, ``trace``, ...)."""
    source: str | None = Field(default=None, max_length=128)


class DecideResponse(BaseModel):
    model: str
    answers: dict[str, dict[str, Any]]
    usage: UsageOut


Granularity = Literal["hour", "day", "week", "month"]


class CostBucket(BaseModel):
    bucket: datetime
    """Start of the period (UTC)."""
    cost: float
    cumulative_cost: float
    """Running total of ``cost`` over the buckets returned, oldest first."""
    calls: int
    total_tokens: int


class CostBreakdown(BaseModel):
    key: str
    cost: float
    calls: int
    total_tokens: int


class CostFacets(BaseModel):
    """Distinct values across all recorded usage, for the filter controls."""

    sources: list[str]
    models: list[str]
    kinds: list[str]
    statuses: list[str]


class CostReport(BaseModel):
    total_cost: float
    total_calls: int
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    first_call_at: datetime | None
    """Start of the first hour with a call (usage is kept per hour)."""
    last_call_at: datetime | None
    """Start of the last hour with a call."""
    granularity: Granularity
    series: list[CostBucket]
    by_source: list[CostBreakdown]
    by_model: list[CostBreakdown]
    by_kind: list[CostBreakdown]
    facets: CostFacets


def _kwargs(payload: _RequestBase) -> dict[str, Any]:
    if payload.prompt is None and not payload.messages:
        raise HTTPException(422, "prompt or messages is required")
    return {
        "prompt": payload.prompt,
        "messages": [m.model_dump() for m in payload.messages] if payload.messages else None,
        "system": payload.system,
        "model": payload.model,
        "temperature": payload.temperature,
        "max_tokens": payload.max_tokens,
    }


def _usage(usage: Usage) -> UsageOut:
    return UsageOut(
        cost=usage.cost,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
    )


def _http_error(exc: OpenRouterError) -> HTTPException:
    if isinstance(exc, OpenRouterNotConfigured):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
    return HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest, service: Annotated[OpenRouterService, Depends(get_openrouter)]
) -> ChatResponse:
    try:
        result = service.chat(source=payload.source or SOURCE_CHAT, **_kwargs(payload))
    except OpenRouterError as exc:
        raise _http_error(exc) from exc
    return ChatResponse(
        model=result.model,
        text=result.text,
        usage=_usage(result.usage),
    )


@router.post("/decide", response_model=DecideResponse)
def decide(
    payload: DecideRequest, service: Annotated[OpenRouterService, Depends(get_openrouter)]
) -> DecideResponse:
    try:
        result = service.decide(
            state=payload.state,
            questions=payload.questions,
            source=payload.source or SOURCE_DECIDE,
            model=payload.model,
            extra=payload.extra,
        )
    except OpenRouterError as exc:
        raise _http_error(exc) from exc
    return DecideResponse(
        model=result.model,
        answers=result.answers,
        usage=_usage(result.usage),
    )


def _bucket_start(ts: datetime, granularity: Granularity) -> datetime:
    ts = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)
    ts = ts.replace(minute=0, second=0, microsecond=0)
    if granularity == "hour":
        return ts
    ts = ts.replace(hour=0)
    if granularity == "day":
        return ts
    if granularity == "week":
        return ts - timedelta(days=ts.weekday())
    return ts.replace(day=1)


def _breakdown(
    rows: list[OpenRouterUsage], key: Callable[[OpenRouterUsage], str]
) -> list[CostBreakdown]:
    groups: dict[str, list[OpenRouterUsage]] = defaultdict(list)
    for row in rows:
        groups[key(row)].append(row)
    out = [
        CostBreakdown(
            key=k,
            cost=sum(r.cost for r in rs),
            calls=sum(r.calls for r in rs),
            total_tokens=sum(r.total_tokens for r in rs),
        )
        for k, rs in groups.items()
    ]
    return sorted(out, key=lambda b: (-b.cost, -b.calls, b.key))


def _distinct(session: Session, column) -> list[str]:
    return list(session.scalars(select(column).distinct().order_by(column)).all())


@router.get("/cost", response_model=CostReport)
def cost_report(
    session: Annotated[Session, Depends(get_session)],
    source: str | None = None,
    kind: str | None = None,
    model: str | None = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
    since: datetime | None = None,
    until: datetime | None = None,
    granularity: Granularity = "day",
) -> CostReport:
    """Spend of the filtered calls: totals, a time series with a running cumulative
    cost, and breakdowns by source / model / kind. Buckets are UTC; empty buckets
    between the first and last call are included so charts have a regular axis.
    Usage is stored per hour, so ``since``/``until`` select whole hours.
    """
    filters = []
    if source:
        filters.append(OpenRouterUsage.source == source)
    if kind:
        filters.append(OpenRouterUsage.kind == kind)
    if model:
        filters.append(OpenRouterUsage.model == model)
    if status_:
        filters.append(OpenRouterUsage.status == status_)
    if since:
        filters.append(OpenRouterUsage.bucket >= _bucket_start(since, "hour"))
    if until:
        filters.append(OpenRouterUsage.bucket < until)

    # The rollup has one row per hour and key, so regrouping in Python is cheap and keeps
    # the date math portable across SQLite and Postgres.
    rows = list(
        session.scalars(
            select(OpenRouterUsage).where(*filters).order_by(OpenRouterUsage.bucket)
        ).all()
    )

    per_bucket: dict[datetime, list[OpenRouterUsage]] = defaultdict(list)
    for row in rows:
        per_bucket[_bucket_start(row.bucket, granularity)].append(row)

    series: list[CostBucket] = []
    if per_bucket:
        running = 0.0
        current = min(per_bucket)
        last = max(per_bucket)
        while current <= last:
            in_bucket = per_bucket.get(current, [])
            cost = sum(r.cost for r in in_bucket)
            running += cost
            series.append(
                CostBucket(
                    bucket=current,
                    cost=cost,
                    cumulative_cost=running,
                    calls=sum(r.calls for r in in_bucket),
                    total_tokens=sum(r.total_tokens for r in in_bucket),
                )
            )
            current = _next_bucket(current, granularity)

    return CostReport(
        total_cost=sum(r.cost for r in rows),
        total_calls=sum(r.calls for r in rows),
        total_tokens=sum(r.total_tokens for r in rows),
        prompt_tokens=sum(r.prompt_tokens for r in rows),
        completion_tokens=sum(r.completion_tokens for r in rows),
        first_call_at=rows[0].bucket if rows else None,
        last_call_at=rows[-1].bucket if rows else None,
        granularity=granularity,
        series=series,
        by_source=_breakdown(rows, lambda r: r.source),
        by_model=_breakdown(rows, lambda r: r.model),
        by_kind=_breakdown(rows, lambda r: r.kind),
        facets=CostFacets(
            sources=_distinct(session, OpenRouterUsage.source),
            models=_distinct(session, OpenRouterUsage.model),
            kinds=_distinct(session, OpenRouterUsage.kind),
            statuses=_distinct(session, OpenRouterUsage.status),
        ),
    )


def _next_bucket(start: datetime, granularity: Granularity) -> datetime:
    if granularity == "hour":
        return start + timedelta(hours=1)
    if granularity == "day":
        return start + timedelta(days=1)
    if granularity == "week":
        return start + timedelta(weeks=1)
    year, month = (start.year + 1, 1) if start.month == 12 else (start.year, start.month + 1)
    return start.replace(year=year, month=month)
