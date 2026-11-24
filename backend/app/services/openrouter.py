"""LLM client shared by the API routes and the background tasks.

Despite the name (kept so the many callers and the ``openrouter_calls`` table need not
change), the provider behind each call is chosen in ``llm.toml`` (``app.services.llm``):
OpenRouter, or any OpenAI-compatible server for chat tasks. Two kinds of call:

* :meth:`OpenRouterService.chat` - plain chat completion that returns text, answered by
  the task's ``ChatProvider``.
* :meth:`OpenRouterService.decide` - a probability ("decision") model: a ``state`` plus
  named typed questions (``noul``/``choice``/``score``/``box``) answered with probabilities
  instead of free text, by the task's ``DecisionProvider`` (OpenRouter's Jev Decisions
  API, https://openrouter.ai/docs/guides/community/jev).

Every call names a ``task`` (its key in ``llm.toml``, which sets the provider, model and
parameters) and a ``source`` (the audit label). Every request, successful or not, is
persisted to ``openrouter_calls`` with the source, the request body, the raw response and
the cost reported by the API (``usage.cost``; ``None`` for providers that report none).

Usage from another route or task::

    from app.services.openrouter import get_openrouter  # FastAPI dependency
    from app.services.openrouter import OpenRouterService

    service = OpenRouterService(session)             # anywhere a Session is at hand
    text = service.chat("Summarise this", task="parse.technologies", source="tasks.parse").text

    decision = service.decide(
        state={"candidate_profile": profile, "job_description": description},
        questions={"is_match": {"type": "noul", "instructions": "Is this a good match?"}},
        task="evaluate.match",
        source="tasks.evaluate",
    )
    probability = decision.noul("is_match")
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Annotated, Any

import httpx
from fastapi import Depends
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.models import OpenRouterCall
from app.services.llm.config import KIND_CHAT, KIND_DECISION, Kind, LlmConfig, ResolvedTask, get_llm_config
from app.services.llm.errors import LlmConfigError, OpenRouterError, OpenRouterNotConfigured
from app.services.llm.providers import HttpRequest, Message, build_chat_provider, build_decision_provider

__all__ = [
    "ChatResult",
    "DecisionResult",
    "LlmConfigError",
    "Message",
    "OpenRouterError",
    "OpenRouterNotConfigured",
    "OpenRouterService",
    "Usage",
    "build_messages",
    "get_openrouter",
    "redact_input",
]


@dataclass(slots=True)
class Usage:
    cost: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    @classmethod
    def from_response(cls, body: dict[str, Any]) -> Usage:
        """Chat completions report ``prompt_tokens``/``completion_tokens``; the decisions
        endpoint reports ``input_tokens``/``output_tokens``. OpenRouter adds ``cost``."""
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
    call_id: int
    """``openrouter_calls.id`` of the persisted record."""
    raw: dict[str, Any] = field(repr=False)


@dataclass(slots=True)
class DecisionResult:
    answers: dict[str, dict[str, Any]]
    """Keyed by question name. ``noul`` answers carry ``noul`` (probability of "yes"),
    ``choice`` answers ``choice`` + ``probabilities``, ``score`` answers ``score`` +
    ``probabilities`` + ``legend``; a ``refusal`` answer has only ``type``."""
    model: str
    usage: Usage
    call_id: int
    raw: dict[str, Any] = field(repr=False)

    def answer(self, name: str, expected_type: str | None = None) -> dict[str, Any]:
        try:
            answer = self.answers[name]
        except KeyError as exc:
            raise OpenRouterError(f"no answer for question {name!r}") from exc
        if expected_type is not None and answer.get("type") != expected_type:
            raise OpenRouterError(f"question {name!r}: expected a {expected_type!r} answer, got {answer.get('type')!r}")
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
    """Synchronous LLM client: resolves a task in ``llm.toml``, lets the task's provider
    build the request, sends it and records it.

    ``session`` is used only to record calls; the caller owns its lifecycle. ``llm_config``
    overrides the file at ``settings.llm_config_path``; ``transport`` lets tests inject an
    ``httpx.MockTransport``.
    """

    def __init__(
        self,
        session: Session,
        settings: Settings | None = None,
        *,
        llm_config: LlmConfig | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self._llm_config = llm_config
        self._transport = transport

    @property
    def llm_config(self) -> LlmConfig:
        return self._llm_config or get_llm_config(self.settings.llm_config_path)

    def resolve(self, task: str, kind: Kind) -> ResolvedTask:
        """Provider, model and parameters ``llm.toml`` sets for ``task``."""
        return self.llm_config.resolve(task, kind)

    # --- public API -------------------------------------------------------------------

    def chat(
        self,
        prompt: str | None = None,
        *,
        task: str,
        source: str,
        messages: list[Message] | None = None,
        system: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        extra: dict[str, Any] | None = None,
        private: bool = False,
    ) -> ChatResult:
        """Free-text chat completion for ``task``. Pass either ``prompt`` (+ optional
        ``system``) or a full ``messages`` list. ``model``/``temperature``/``max_tokens``
        override the task's config and ``extra`` is merged over its ``extra``. With
        ``private`` the user/assistant message contents are not stored in
        ``openrouter_calls.input`` (see ``redact_input``)."""
        resolved = self.resolve(task, KIND_CHAT)
        provider = build_chat_provider(resolved.provider_name, resolved.provider, self.settings)
        request = provider.chat_request(
            model or resolved.model,
            self._messages(prompt, messages, system),
            temperature=temperature if temperature is not None else resolved.temperature,
            max_tokens=max_tokens if max_tokens is not None else resolved.max_tokens,
            extra={**resolved.extra, **(extra or {})},
        )
        raw, usage, call = self._call(request, source=source, kind=OpenRouterCall.KIND_CHAT, private=private)
        try:
            text = provider.chat_text(raw)
        except OpenRouterError as exc:
            self._mark_failed(call, str(exc))
            raise
        return ChatResult(
            text=text,
            model=raw.get("model", request.body["model"]),
            usage=usage,
            call_id=call.id,
            raw=raw,
        )

    def decide(
        self,
        *,
        state: str | dict[str, Any] | list[Any],
        questions: dict[str, dict[str, Any]],
        task: str,
        source: str,
        model: str | None = None,
        extra: dict[str, Any] | None = None,
        private: bool = False,
    ) -> DecisionResult:
        """Probability-model call for ``task``. ``state`` is the content to judge (string,
        object or array); ``questions`` maps a name of your choice to a question such as
        ``{"type": "noul", "instructions": "...", "criteria": {"true": "...", "false": "..."}}``.
        ``extra`` is merged into the request body (``assets``, ``provider``, ``trace``, ...).
        With ``private`` the ``state`` is not stored in ``openrouter_calls.input``.
        """
        if not questions:
            raise ValueError("at least one question is required")
        resolved = self.resolve(task, KIND_DECISION)
        provider = build_decision_provider(resolved.provider_name, resolved.provider, self.settings)
        request = provider.decision_request(
            model or resolved.model,
            state,
            questions,
            extra={**resolved.extra, **(extra or {})},
        )
        raw, usage, call = self._call(request, source=source, kind=OpenRouterCall.KIND_DECISION, private=private)
        try:
            answers = provider.decision_answers(raw)
        except OpenRouterError as exc:
            self._mark_failed(call, str(exc))
            raise
        return DecisionResult(
            answers=answers,
            model=raw.get("model", request.body["model"]),
            usage=usage,
            call_id=call.id,
            raw=raw,
        )

    # --- internals --------------------------------------------------------------------

    @staticmethod
    def _messages(prompt: str | None, messages: list[Message] | None, system: str | None) -> list[Message]:
        if messages:
            return list(messages)
        if prompt is None:
            raise ValueError("either prompt or messages is required")
        return build_messages(prompt, system)

    def _call(
        self,
        request: HttpRequest,
        *,
        source: str,
        kind: str,
        private: bool = False,
    ) -> tuple[dict[str, Any], Usage, OpenRouterCall]:
        """POST ``request``, record the call and return the parsed JSON response. With
        ``private`` the recorded input is ``redact_input(body)``."""
        body = request.body
        call = OpenRouterCall(
            source=source,
            kind=kind,
            model=body["model"],
            input=redact_input(body) if private else body,
        )
        self.session.add(call)
        self.session.commit()

        started = time.perf_counter()
        try:
            with httpx.Client(timeout=request.timeout, transport=self._transport) as client:
                response = client.post(request.url, json=body, headers=request.headers)
        except httpx.HTTPError as exc:
            self._mark_failed(call, f"request failed: {exc}", started)
            raise OpenRouterError(f"LLM request failed: {exc}") from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        try:
            raw = response.json()
        except ValueError:
            raw = None
        if response.status_code >= 400 or not isinstance(raw, dict):
            detail = self._error_detail(raw, response.text)
            self._mark_failed(call, f"HTTP {response.status_code}: {detail}", started, raw)
            raise OpenRouterError(
                f"LLM provider returned HTTP {response.status_code}: {detail}",
                status_code=response.status_code,
            )
        # OpenRouter may answer 200 with an ``error`` object (e.g. provider failure).
        if "error" in raw and request.result_key not in raw:
            detail = self._error_detail(raw, response.text)
            self._mark_failed(call, detail, started, raw)
            raise OpenRouterError(f"LLM provider error: {detail}")

        usage = Usage.from_response(raw)
        call.status = OpenRouterCall.STATUS_OK
        call.output = raw
        call.cost = usage.cost
        call.prompt_tokens = usage.prompt_tokens
        call.completion_tokens = usage.completion_tokens
        call.total_tokens = usage.total_tokens
        call.generation_id = raw.get("id")
        call.model = raw.get("model") or call.model
        call.latency_ms = latency_ms
        self.session.commit()
        return raw, usage, call

    @staticmethod
    def _error_detail(raw: object, text: str) -> str:
        if isinstance(raw, dict):
            error = raw.get("error")
            if isinstance(error, dict) and error.get("message"):
                return str(error["message"])
            if error:
                return str(error)
        return text[:500]

    def _mark_failed(
        self,
        call: OpenRouterCall,
        error: str,
        started: float | None = None,
        raw: object = None,
    ) -> None:
        call.status = OpenRouterCall.STATUS_FAILED
        call.error = error
        if isinstance(raw, dict):
            call.output = raw
        if started is not None:
            call.latency_ms = int((time.perf_counter() - started) * 1000)
        self.session.commit()


REDACTED = "[not stored]"


def redact_input(body: dict[str, Any]) -> dict[str, Any]:
    """Copy of a request body without its private content, for ``openrouter_calls.input``:
    the decision ``state`` and the user/assistant message contents are replaced (system
    prompts, questions and parameters are kept). Marked with ``"redacted": True``."""
    redacted = {key: value for key, value in body.items() if key not in ("state", "messages")}
    if "state" in body:
        redacted["state"] = REDACTED
    if "messages" in body:
        redacted["messages"] = [m if m.get("role") == "system" else {**m, "content": REDACTED} for m in body["messages"]]
    redacted["redacted"] = True
    return redacted


def get_openrouter(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[OpenRouterService]:
    """FastAPI dependency: ``service: Annotated[OpenRouterService, Depends(get_openrouter)]``."""
    yield OpenRouterService(session, settings)
