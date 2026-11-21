"""OpenRouter client shared by the API routes and the background tasks.

Two kinds of call are supported:

* :meth:`OpenRouterService.chat` - plain chat completion (``/v1/chat/completions``) that
  returns text.
* :meth:`OpenRouterService.decide` - Jev Decisions API (``/alpha/decisions``): a ``state``
  plus named typed questions (``noul``/``choice``/``score``/``box``) answered with
  probabilities instead of free text. See https://openrouter.ai/docs/guides/community/jev.

Every request, successful or not, is added to the hourly ``openrouter_usage`` rollup for
its (source, model, kind, status): call count, tokens and the cost reported by the API
(``usage.cost``; chat requests ask for it via ``usage: {"include": true}``, the decisions
endpoint always returns it). Prompts and responses are not stored.

Usage from another route or task::

    from app.services.openrouter import get_openrouter  # FastAPI dependency
    from app.services.openrouter import OpenRouterService

    service = OpenRouterService(session)             # anywhere a Session is at hand
    text = service.chat("Summarise this", source="tasks.parse").text

    decision = service.decide(
        state={"candidate_profile": profile, "job_description": description},
        questions={"is_match": {"type": "noul", "instructions": "Is this a good match?"}},
        source="tasks.evaluate",
    )
    probability = decision.noul("is_match")
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any

import httpx
from fastapi import Depends
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.models import OpenRouterUsage

Message = dict[str, Any]


class OpenRouterError(Exception):
    """Raised when OpenRouter cannot be called or returns an unusable response."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class OpenRouterNotConfigured(OpenRouterError):
    """``OPENROUTER_API_KEY`` is empty."""


@dataclass(slots=True)
class Usage:
    cost: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    @classmethod
    def from_response(cls, body: dict[str, Any]) -> Usage:
        """Chat completions report ``prompt_tokens``/``completion_tokens``; the decisions
        endpoint reports ``input_tokens``/``output_tokens``. Both carry ``cost``."""
        usage = body.get("usage") or {}
        prompt = _as_int(usage.get("prompt_tokens", usage.get("input_tokens")))
        completion = _as_int(usage.get("completion_tokens", usage.get("output_tokens")))
        total = _as_int(usage.get("total_tokens"))
        if total is None and prompt is not None and completion is not None:
            total = prompt + completion
        return cls(
            cost=_as_float(usage.get("cost")),
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
        )


@dataclass(slots=True)
class ChatResult:
    text: str
    model: str
    usage: Usage
    raw: dict[str, Any] = field(repr=False)


@dataclass(slots=True)
class DecisionResult:
    answers: dict[str, dict[str, Any]]
    """Keyed by question name. ``noul`` answers carry ``noul`` (probability of "yes"),
    ``choice`` answers ``choice`` + ``probabilities``, ``score`` answers ``score`` +
    ``probabilities`` + ``legend``; a ``refusal`` answer has only ``type``."""
    model: str
    usage: Usage
    raw: dict[str, Any] = field(repr=False)

    def answer(self, name: str, expected_type: str | None = None) -> dict[str, Any]:
        try:
            answer = self.answers[name]
        except KeyError as exc:
            raise OpenRouterError(f"no answer for question {name!r}") from exc
        if expected_type is not None and answer.get("type") != expected_type:
            raise OpenRouterError(
                f"question {name!r}: expected a {expected_type!r} answer, "
                f"got {answer.get('type')!r}"
            )
        return answer

    def noul(self, name: str) -> float:
        """Probability of "yes" for a ``noul`` question."""
        return float(self.answer(name, "noul")["noul"])

    def choice(self, name: str) -> str:
        return str(self.answer(name, "choice")["choice"])

    def score(self, name: str) -> float:
        return float(self.answer(name, "score")["score"])


def _as_float(value: object) -> float | None:
    try:
        return None if value is None else float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _as_int(value: object) -> int | None:
    try:
        return None if value is None else int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def build_messages(prompt: str, system: str | None = None) -> list[Message]:
    messages: list[Message] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return messages


class OpenRouterService:
    """Thin synchronous wrapper around the OpenRouter chat completions endpoint.

    ``session`` is used only to record usage; the caller owns its lifecycle. ``transport``
    lets tests inject an ``httpx.MockTransport``.
    """

    def __init__(
        self,
        session: Session,
        settings: Settings | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self._transport = transport

    # --- public API -------------------------------------------------------------------

    def chat(
        self,
        prompt: str | None = None,
        *,
        source: str,
        messages: list[Message] | None = None,
        system: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> ChatResult:
        """Free-text chat completion. Pass either ``prompt`` (+ optional ``system``) or a
        full ``messages`` list."""
        body = self._body(
            model or self.settings.openrouter_chat_model,
            self._messages(prompt, messages, system),
            temperature=temperature,
            max_tokens=max_tokens,
            extra=extra,
        )
        url = f"{self.settings.openrouter_base_url.rstrip('/')}/chat/completions"
        raw, usage = self._call(
            url, body, source=source, kind=OpenRouterUsage.KIND_CHAT, result_key="choices"
        )
        return ChatResult(
            text=self._content(raw),
            model=raw.get("model", body["model"]),
            usage=usage,
            raw=raw,
        )

    def decide(
        self,
        *,
        state: str | dict[str, Any] | list[Any],
        questions: dict[str, dict[str, Any]],
        source: str,
        model: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> DecisionResult:
        """Jev Decisions API call. ``state`` is the content to judge (string, object or
        array); ``questions`` maps a name of your choice to a question such as
        ``{"type": "noul", "instructions": "...", "criteria": {"true": "...", "false": "..."}}``.
        ``extra`` is merged into the request body (``assets``, ``provider``, ``trace``, ...).
        """
        if not questions:
            raise ValueError("at least one question is required")
        body: dict[str, Any] = {
            "model": model or self.settings.openrouter_decision_model,
            "state": state,
            "questions": questions,
        }
        if extra:
            body.update(extra)
        raw, usage = self._call(
            self.settings.openrouter_decisions_url,
            body,
            source=source,
            kind=OpenRouterUsage.KIND_DECISION,
            result_key="answers",
        )
        answers = raw.get("answers")
        if not isinstance(answers, dict):
            raise OpenRouterError("response has no answers object")
        return DecisionResult(
            answers=answers,
            model=raw.get("model", body["model"]),
            usage=usage,
            raw=raw,
        )

    # --- internals --------------------------------------------------------------------

    @staticmethod
    def _messages(
        prompt: str | None, messages: list[Message] | None, system: str | None
    ) -> list[Message]:
        if messages:
            return list(messages)
        if prompt is None:
            raise ValueError("either prompt or messages is required")
        return build_messages(prompt, system)

    @staticmethod
    def _body(
        model: str,
        messages: list[Message],
        *,
        temperature: float | None,
        max_tokens: int | None,
        extra: dict[str, Any] | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            # Ask OpenRouter to include the cost of the call in the response.
            "usage": {"include": True},
        }
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if extra:
            body.update(extra)
        return body

    @staticmethod
    def _content(raw: dict[str, Any]) -> str:
        try:
            content = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenRouterError("response has no choices[0].message.content") from exc
        if isinstance(content, list):  # multi-part content; keep the text parts
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return content if isinstance(content, str) else str(content)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "Content-Type": "application/json",
        }
        if self.settings.openrouter_site_url:
            headers["HTTP-Referer"] = self.settings.openrouter_site_url
        if self.settings.openrouter_site_name:
            headers["X-Title"] = self.settings.openrouter_site_name
        return headers

    def _call(
        self, url: str, body: dict[str, Any], *, source: str, kind: str, result_key: str
    ) -> tuple[dict[str, Any], Usage]:
        """POST ``body`` to ``url``, add the call to the usage rollup and return the parsed
        JSON response. ``result_key`` is the field a successful response must contain."""
        if not self.settings.openrouter_api_key:
            raise OpenRouterNotConfigured("OPENROUTER_API_KEY is not set")

        model = body["model"]
        try:
            with httpx.Client(
                timeout=self.settings.openrouter_timeout, transport=self._transport
            ) as client:
                response = client.post(url, json=body, headers=self._headers())
        except httpx.HTTPError as exc:
            self._record(source, kind, model, OpenRouterUsage.STATUS_FAILED)
            raise OpenRouterError(f"OpenRouter request failed: {exc}") from exc

        try:
            raw = response.json()
        except ValueError:
            raw = None
        if response.status_code >= 400 or not isinstance(raw, dict):
            detail = self._error_detail(raw, response.text)
            self._record(source, kind, model, OpenRouterUsage.STATUS_FAILED)
            raise OpenRouterError(
                f"OpenRouter returned HTTP {response.status_code}: {detail}",
                status_code=response.status_code,
            )
        usage = Usage.from_response(raw)
        model = raw.get("model") or model
        # OpenRouter may answer 200 with an ``error`` object (e.g. provider failure).
        if "error" in raw and result_key not in raw:
            self._record(source, kind, model, OpenRouterUsage.STATUS_FAILED, usage)
            raise OpenRouterError(f"OpenRouter error: {self._error_detail(raw, response.text)}")

        self._record(source, kind, model, OpenRouterUsage.STATUS_OK, usage)
        return raw, usage

    def _record(
        self, source: str, kind: str, model: str, status: str, usage: Usage | None = None
    ) -> None:
        """Add one call to its hourly ``openrouter_usage`` bucket with an atomic upsert,
        so concurrent callers (e.g. the CV task's thread pool) never lose increments."""
        increments = {
            "calls": 1,
            "cost": (usage.cost if usage else None) or 0.0,
            "prompt_tokens": (usage.prompt_tokens if usage else None) or 0,
            "completion_tokens": (usage.completion_tokens if usage else None) or 0,
            "total_tokens": (usage.total_tokens if usage else None) or 0,
        }
        bucket = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        dialect = self.session.get_bind().dialect.name
        insert = pg_insert if dialect == "postgresql" else sqlite_insert
        table = OpenRouterUsage.__table__
        stmt = insert(table).values(
            bucket=bucket, source=source, model=model, kind=kind, status=status, **increments
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["bucket", "source", "model", "kind", "status"],
            set_={name: table.c[name] + stmt.excluded[name] for name in increments},
        )
        self.session.execute(stmt)
        self.session.commit()

    @staticmethod
    def _error_detail(raw: object, text: str) -> str:
        if isinstance(raw, dict):
            error = raw.get("error")
            if isinstance(error, dict) and error.get("message"):
                return str(error["message"])
            if error:
                return str(error)
        return text[:500]


def get_openrouter(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[OpenRouterService]:
    """FastAPI dependency: ``service: Annotated[OpenRouterService, Depends(get_openrouter)]``."""
    yield OpenRouterService(session, settings)
