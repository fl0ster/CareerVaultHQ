"""OpenRouter: free-text chat (``POST /chat``), Jev decisions (``POST /decide``)
and the audit log of every call made through ``app.services.openrouter``
(``GET /calls``, ``GET /calls/{id}``).

Other routes/tasks should not go through HTTP; they use ``OpenRouterService`` directly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import OpenRouterCall
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
    call_id: int
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
    call_id: int
    model: str
    answers: dict[str, dict[str, Any]]
    usage: UsageOut


class OpenRouterCallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    kind: str
    model: str
    status: str
    cost: float | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    generation_id: str | None
    latency_ms: int | None
    error: str | None
    created_at: datetime


class OpenRouterCallDetailOut(OpenRouterCallOut):
    input: dict[str, Any]
    output: dict[str, Any] | None


class OpenRouterCallsPage(BaseModel):
    total: int
    total_cost: float
    items: list[OpenRouterCallOut]


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
        call_id=result.call_id,
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
        call_id=result.call_id,
        model=result.model,
        answers=result.answers,
        usage=_usage(result.usage),
    )


@router.get("/calls", response_model=OpenRouterCallsPage)
def list_calls(
    session: Annotated[Session, Depends(get_session)],
    source: str | None = None,
    kind: str | None = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> OpenRouterCallsPage:
    """Calls newest first, with the total count and summed cost of the filtered set."""
    filters = []
    if source:
        filters.append(OpenRouterCall.source == source)
    if kind:
        filters.append(OpenRouterCall.kind == kind)
    if status_:
        filters.append(OpenRouterCall.status == status_)

    total, total_cost = session.execute(
        select(
            func.count(OpenRouterCall.id), func.coalesce(func.sum(OpenRouterCall.cost), 0.0)
        ).where(*filters)
    ).one()
    items = session.scalars(
        select(OpenRouterCall)
        .where(*filters)
        .order_by(OpenRouterCall.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return OpenRouterCallsPage(
        total=total,
        total_cost=float(total_cost),
        items=[OpenRouterCallOut.model_validate(c) for c in items],
    )


@router.get("/calls/{call_id}", response_model=OpenRouterCallDetailOut)
def get_call(call_id: int, session: Annotated[Session, Depends(get_session)]) -> OpenRouterCall:
    call = session.get(OpenRouterCall, call_id)
    if call is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown openrouter call")
    return call
