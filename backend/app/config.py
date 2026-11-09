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

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("frontend_dist", mode="before")
    @classmethod
    def _resolve_dist(cls, value: object) -> object:
        if isinstance(value, str):
            path = Path(value)
            return path if path.is_absolute() else (BACKEND_DIR / path).resolve()
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
