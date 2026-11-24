"""Errors raised by the LLM layer (``app.services.openrouter`` and its providers).

The ``OpenRouter*`` names predate pluggable providers; they are kept because every task
catches them. They are raised for any provider, not only OpenRouter.
"""

from __future__ import annotations


class OpenRouterError(Exception):
    """Raised when an LLM provider cannot be called or returns an unusable response."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class OpenRouterNotConfigured(OpenRouterError):
    """The provider a task uses needs an API key and its env var is empty."""


class LlmConfigError(Exception):
    """``llm.toml`` is invalid, or a task is not defined in it. Deliberately not an
    ``OpenRouterError``: it is a configuration mistake, not a failed call, so the tasks'
    retry/fallback handling must not swallow it."""
