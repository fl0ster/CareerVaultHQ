"""``llm.toml``: the one place where the provider, model and parameters of every LLM task
are set.

The file has three sections (see the shipped ``app/llm.toml`` for a commented example)::

    [providers.<name>]      # where requests go: type, base_url, api_key_env, timeout, ...
    [defaults.chat]         # provider + model (+ optional params) of every chat task
    [defaults.decision]     # same for every decision (Jev probability) task
    [tasks."<task key>"]    # kind, description and per-task overrides

Code refers to a task by its key (``service.chat(..., task="cv.summary")``) and never
hard-codes a model or a sampling parameter. :meth:`LlmConfig.resolve` merges the kind's
defaults with the task entry; explicit arguments to ``chat``/``decide`` win over both.

The file is parsed with the standard library (``tomllib``) and re-read when its mtime
changes, so a tweak takes effect on the next call without restarting the worker.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.services.llm.errors import LlmConfigError

Kind = Literal["chat", "decision"]
KIND_CHAT: Kind = "chat"
KIND_DECISION: Kind = "decision"

ProviderType = Literal["openrouter", "openai_compatible"]
DECISION_PROVIDER_TYPES: frozenset[str] = frozenset({"openrouter"})
"""Provider types that implement ``DecisionProvider`` (see ``providers.py``)."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderConfig(_Strict):
    type: ProviderType
    """``openrouter``: chat completions + Jev decisions; ``openai_compatible``: chat only
    (OpenAI, Ollama, LM Studio, vLLM, llama.cpp server, ...)."""
    base_url: str
    """Base of the OpenAI-style API; ``/chat/completions`` is appended."""
    decisions_url: str | None = None
    """Jev Decisions endpoint (``openrouter`` only)."""
    api_key_env: str = ""
    """Name of the env var (or ``Settings`` field, see ``api_key``) holding the key. Empty
    means no ``Authorization`` header (fine for a local server)."""
    timeout: float = Field(default=120.0, gt=0)
    """Per-request HTTP timeout (seconds)."""
    site_url: str = ""
    """``openrouter`` only: optional ``HTTP-Referer`` attribution header."""
    site_name: str = ""
    """``openrouter`` only: optional ``X-Title`` attribution header."""

    @model_validator(mode="after")
    def _check(self) -> ProviderConfig:
        if self.type == "openrouter" and not self.decisions_url:
            raise ValueError("an openrouter provider needs decisions_url")
        if self.type != "openrouter" and (self.decisions_url or self.site_url or self.site_name):
            raise ValueError("decisions_url / site_url / site_name only apply to an openrouter provider")
        return self

    @property
    def supports_decisions(self) -> bool:
        return self.type in DECISION_PROVIDER_TYPES


class _Params(_Strict):
    provider: str | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1)
    extra: dict[str, Any] = Field(default_factory=dict)
    """Merged into the request body (e.g. ``top_p``, ``reasoning``, ``provider``)."""


class DefaultsConfig(_Params):
    provider: str
    model: str


class Defaults(_Strict):
    chat: DefaultsConfig
    decision: DefaultsConfig


class TaskConfig(_Params):
    kind: Kind
    description: str = ""
    """What the task does, where it is called and why its parameters are what they are."""


@dataclass(frozen=True, slots=True)
class ResolvedTask:
    """Everything needed to make one call for a task."""

    task: str
    kind: Kind
    provider_name: str
    provider: ProviderConfig
    model: str
    temperature: float | None = None
    max_tokens: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class LlmConfig(_Strict):
    providers: dict[str, ProviderConfig] = Field(min_length=1)
    defaults: Defaults
    tasks: dict[str, TaskConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_providers(self) -> LlmConfig:
        for kind in (KIND_CHAT, KIND_DECISION):
            self._check_provider(f"defaults.{kind}", kind, getattr(self.defaults, kind).provider)
        for key, task in self.tasks.items():
            if task.provider is not None:
                self._check_provider(f'tasks."{key}"', task.kind, task.provider)
        return self

    def _check_provider(self, where: str, kind: Kind, name: str) -> None:
        provider = self.providers.get(name)
        if provider is None:
            raise ValueError(f"{where}: unknown provider {name!r} (defined: {', '.join(sorted(self.providers))})")
        if kind == KIND_DECISION and not provider.supports_decisions:
            raise ValueError(
                f"{where}: provider {name!r} ({provider.type}) cannot answer decision tasks; "
                f"use one of type {', '.join(sorted(DECISION_PROVIDER_TYPES))}"
            )

    def resolve(self, task: str, kind: Kind) -> ResolvedTask:
        """Provider, model and parameters for ``task``: the task entry over the kind's
        defaults. Raises :class:`LlmConfigError` for an unknown task or a kind mismatch."""
        entry = self.tasks.get(task)
        if entry is None:
            raise LlmConfigError(f'LLM task {task!r} is not defined; add [tasks."{task}"] to llm.toml')
        if entry.kind != kind:
            raise LlmConfigError(f"LLM task {task!r} is a {entry.kind} task, not {kind}")
        defaults: DefaultsConfig = getattr(self.defaults, kind)
        provider_name = entry.provider or defaults.provider
        return ResolvedTask(
            task=task,
            kind=kind,
            provider_name=provider_name,
            provider=self.providers[provider_name],
            model=entry.model or defaults.model,
            temperature=entry.temperature if entry.temperature is not None else defaults.temperature,
            max_tokens=entry.max_tokens if entry.max_tokens is not None else defaults.max_tokens,
            extra={**defaults.extra, **entry.extra},
        )


def parse_llm_config(data: dict[str, Any], *, origin: str = "llm config") -> LlmConfig:
    try:
        return LlmConfig.model_validate(data)
    except ValidationError as exc:
        raise LlmConfigError(f"{origin} is invalid:\n{exc}") from exc


def load_llm_config(path: Path) -> LlmConfig:
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except OSError as exc:
        raise LlmConfigError(f"cannot read LLM config {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise LlmConfigError(f"LLM config {path} is not valid TOML: {exc}") from exc
    return parse_llm_config(data, origin=str(path))


@lru_cache(maxsize=4)
def _load_cached(path: Path, _mtime_ns: int) -> LlmConfig:
    return load_llm_config(path)


def get_llm_config(path: Path) -> LlmConfig:
    """``load_llm_config`` cached until the file's mtime changes."""
    try:
        mtime = path.stat().st_mtime_ns
    except OSError as exc:
        raise LlmConfigError(f"cannot read LLM config {path}: {exc}") from exc
    return _load_cached(path, mtime)


def api_key(provider: ProviderConfig, settings: object) -> str:
    """The key named by ``provider.api_key_env``. When ``Settings`` has a field of that
    name (lower-cased: ``OPENROUTER_API_KEY``, ``LOCAL_LLM_API_KEY``) it is used, so the key
    can also come from ``backend/.env``; any other name is read from the process
    environment. Empty when unset or when the provider names no key."""
    if not provider.api_key_env:
        return ""
    value = getattr(settings, provider.api_key_env.lower(), None)
    if isinstance(value, str):
        return value
    return os.environ.get(provider.api_key_env, "")
