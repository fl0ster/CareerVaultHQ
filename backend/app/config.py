from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "CareerVaultHQ"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    api_prefix: str = "/api"
    # NoDecode: read the raw env string and let _split_origins parse the comma list.
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    frontend_dist: Path = BACKEND_DIR.parent / "frontend" / "dist"
    # SQLAlchemy URL. Defaults to a local SQLite file for development/tests;
    # docker-compose points it at the persistent /data volume (sqlite:////data/careervault.db).
    database_url: str = f"sqlite:///{BACKEND_DIR / 'careervault.db'}"

    # --- Background jobs (Redis Queue) ---
    # docker-compose points this at the bundled redis service (redis://redis:6379/0).
    redis_url: str = "redis://localhost:6379/0"
    queue_name: str = "jobs"
    # How long a finished/failed job stays queryable via GET /latex/jobs/{id} (seconds).
    job_result_ttl: int = 3600

    # --- LaTeX -> PDF ---
    latex_upload_root: Path = BACKEND_DIR / "static" / "uploads"
    latex_jobs_root: Path = BACKEND_DIR / "static" / "jobs"
    latex_compiler: str = "pdflatex"
    # pdflatex is run this many times so cross-references / layout settle.
    latex_passes: int = 2
    # Hard limit per compile job (seconds); the Pi 2 is slow, so be generous.
    latex_timeout: int = 300
    # Reject uploads larger than this (bytes).
    latex_max_upload_bytes: int = 2 * 1024 * 1024

    # --- OpenRouter (LLM calls) ---
    # API key from https://openrouter.ai/keys. Calls fail with 503 when it is empty.
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # Default model for free-text chat completions.
    openrouter_chat_model: str = "openai/gpt-4o-mini"
    # Jev Decisions API (https://openrouter.ai/docs/guides/community/jev): typed answers
    # (probabilities) to questions about a ``state`` instead of free text.
    openrouter_decisions_url: str = "https://openrouter.ai/api/alpha/decisions"
    openrouter_decision_model: str = "typesafe/jev-1.14"
    # Per-request HTTP timeout (seconds).
    openrouter_timeout: float = 120.0
    # Optional attribution headers shown on openrouter.ai rankings.
    openrouter_site_url: str = ""
    openrouter_site_name: str = "CareerVaultHQ"

    # --- Job evaluation (app.tasks.evaluate / app.scheduler) ---
    # How often the scheduler enqueues a catch-up ``evaluate_pending_jobs`` run (seconds).
    evaluate_interval_seconds: int = 15 * 60
    # Longest the scheduler waits after consecutive failed catch-up runs (seconds).
    evaluate_max_backoff_seconds: int = 6 * 3600
    # Jobs scored per catch-up run, so one run does not hog the single worker.
    evaluate_batch_size: int = 50
    # A (job, profile) pair whose OpenRouter call failed is retried after
    # ``evaluate_retry_backoff_seconds * 2**(attempts-1)``, at most ``evaluate_max_attempts`` times.
    evaluate_max_attempts: int = 3
    evaluate_retry_backoff_seconds: int = 30 * 60

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("frontend_dist", "latex_upload_root", "latex_jobs_root", mode="before")
    @classmethod
    def _resolve_path(cls, value: object) -> object:
        if isinstance(value, str):
            path = Path(value)
            return path if path.is_absolute() else (BACKEND_DIR / path).resolve()
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
