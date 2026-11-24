"""LLM providers: how a request for a task is built and how its response is read.

A provider only translates; it does no HTTP and no logging. ``OpenRouterService`` sends
the :class:`HttpRequest` a provider builds, records it in ``openrouter_calls`` and hands the
JSON body back to the provider to parse. Two roles:

* :class:`ChatProvider` - free-text chat completions. Implemented by
  :class:`OpenAICompatibleChat` (any ``/chat/completions`` server: OpenAI, Ollama, LM
  Studio, vLLM, llama.cpp, ...) and :class:`OpenRouterChat`.
* :class:`DecisionProvider` - probability ("decision") models: a ``state`` plus named typed
  questions, answered with probabilities instead of text. The answer contract is the Jev
  shape, ``{"<name>": {"type": "noul", "noul": <P(yes)>}, ...}`` (plus ``choice``/``score``
  answers), which ``DecisionResult`` reads. Implemented by :class:`JevDecisions`
  (OpenRouter's Jev Decisions API). Another probability backend (e.g. P("yes") from the
  token logprobs of a chat model) plugs in by implementing this protocol, adding its type to
  ``DECISION_PROVIDER_TYPES`` and to :func:`build_decision_provider`.

Chat and decision tasks pick their providers independently in ``llm.toml``, so chat can
run on a local model while decisions stay on OpenRouter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.services.llm.config import ProviderConfig, api_key
from app.services.llm.errors import LlmConfigError, OpenRouterError, OpenRouterNotConfigured

Message = dict[str, Any]

CHAT_RESULT_KEY = "choices"
DECISION_RESULT_KEY = "answers"


@dataclass(frozen=True, slots=True)
class HttpRequest:
    url: str
    body: dict[str, Any]
    headers: dict[str, str] = field(repr=False)
    timeout: float
    result_key: str
    """Field a successful response must contain (an ``error`` body without it fails)."""


class ChatProvider(Protocol):
    def chat_request(
        self,
        model: str,
        messages: list[Message],
        *,
        temperature: float | None,
        max_tokens: int | None,
        extra: dict[str, Any],
    ) -> HttpRequest: ...

    def chat_text(self, raw: dict[str, Any]) -> str: ...


class DecisionProvider(Protocol):
    def decision_request(
        self,
        model: str,
        state: str | dict[str, Any] | list[Any],
        questions: dict[str, dict[str, Any]],
        *,
        extra: dict[str, Any],
    ) -> HttpRequest: ...

    def decision_answers(self, raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Answers keyed by question name; raises ``OpenRouterError`` when missing."""
        ...


# --- chat ---------------------------------------------------------------------------------


class OpenAICompatibleChat:
    """``POST {base_url}/chat/completions`` with a standard OpenAI body. Sends an
    ``Authorization`` header only when a key is configured."""

    def __init__(self, config: ProviderConfig, key: str) -> None:
        self.config = config
        self.key = key

    def headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        return headers

    def body(
        self,
        model: str,
        messages: list[Message],
        *,
        temperature: float | None,
        max_tokens: int | None,
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"model": model, "messages": messages}
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        body.update(extra)
        return body

    def chat_request(
        self,
        model: str,
        messages: list[Message],
        *,
        temperature: float | None,
        max_tokens: int | None,
        extra: dict[str, Any],
    ) -> HttpRequest:
        return HttpRequest(
            url=f"{self.config.base_url.rstrip('/')}/chat/completions",
            body=self.body(model, messages, temperature=temperature, max_tokens=max_tokens, extra=extra),
            headers=self.headers(),
            timeout=self.config.timeout,
            result_key=CHAT_RESULT_KEY,
        )

    def chat_text(self, raw: dict[str, Any]) -> str:
        try:
            content = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenRouterError("response has no choices[0].message.content") from exc
        if isinstance(content, list):  # multi-part content; keep the text parts
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        if content is None:  # some servers send null content for an empty answer
            return ""
        return content if isinstance(content, str) else str(content)


def _openrouter_headers(config: ProviderConfig, key: str) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if config.site_url:
        headers["HTTP-Referer"] = config.site_url
    if config.site_name:
        headers["X-Title"] = config.site_name
    return headers


class OpenRouterChat(OpenAICompatibleChat):
    """OpenAI-style chat on OpenRouter, plus its extras: the cost of the call in the
    response (``usage: {"include": true}``) and the attribution headers."""

    def headers(self) -> dict[str, str]:
        return _openrouter_headers(self.config, self.key)

    def body(
        self,
        model: str,
        messages: list[Message],
        *,
        temperature: float | None,
        max_tokens: int | None,
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        body = super().body(model, messages, temperature=temperature, max_tokens=max_tokens, extra={})
        body["usage"] = {"include": True}
        body.update(extra)
        return body


# --- decisions ----------------------------------------------------------------------------


class JevDecisions:
    """OpenRouter's Jev Decisions API (https://openrouter.ai/docs/guides/community/jev)."""

    def __init__(self, config: ProviderConfig, key: str) -> None:
        if not config.decisions_url:  # ProviderConfig validation requires it for openrouter
            raise LlmConfigError("a Jev decisions provider needs decisions_url")
        self.config = config
        self.url = config.decisions_url
        self.key = key

    def decision_request(
        self,
        model: str,
        state: str | dict[str, Any] | list[Any],
        questions: dict[str, dict[str, Any]],
        *,
        extra: dict[str, Any],
    ) -> HttpRequest:
        return HttpRequest(
            url=self.url,
            body={"model": model, "state": state, "questions": questions, **extra},
            headers=_openrouter_headers(self.config, self.key),
            timeout=self.config.timeout,
            result_key=DECISION_RESULT_KEY,
        )

    def decision_answers(self, raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
        answers = raw.get("answers")
        if not isinstance(answers, dict):
            raise OpenRouterError("response has no answers object")
        return answers


# --- factories ----------------------------------------------------------------------------


def _key(name: str, config: ProviderConfig, settings: object, *, required: bool) -> str:
    key = api_key(config, settings)
    if required and not key:
        env = config.api_key_env or "(api_key_env not set)"
        raise OpenRouterNotConfigured(f"{env} is not set (needed by LLM provider {name!r})")
    return key


def build_chat_provider(name: str, config: ProviderConfig, settings: object) -> ChatProvider:
    """Raises ``OpenRouterNotConfigured`` when the provider needs a key that is not set."""
    if config.type == "openrouter":
        return OpenRouterChat(config, _key(name, config, settings, required=True))
    if config.type == "openai_compatible":
        return OpenAICompatibleChat(config, _key(name, config, settings, required=False))
    raise LlmConfigError(f"LLM provider {name!r}: unsupported type {config.type!r}")


def build_decision_provider(name: str, config: ProviderConfig, settings: object) -> DecisionProvider:
    """Raises ``OpenRouterNotConfigured`` when the provider needs a key that is not set."""
    if config.type == "openrouter":
        return JevDecisions(config, _key(name, config, settings, required=True))
    raise LlmConfigError(f"LLM provider {name!r} ({config.type}) cannot answer decision tasks")
