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
    latex_queue_name: str = "latex_2_pdf"
    scrapper_queue_name: str = "scrapper"
    # How long a finished/failed job stays queryable via GET /latex/jobs/{id} (seconds).
    job_result_ttl: int = 24 * 3600

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
