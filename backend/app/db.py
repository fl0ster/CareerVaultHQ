"""SQLAlchemy engine / session shared by the API and the workers.

The schema is created with ``init_db()`` (``Base.metadata.create_all``) at API and
worker startup; there is no Alembic migration history yet. ``create_all`` never alters an
existing table, so ``init_db`` also adds the columns listed in ``ADDED_COLUMNS`` to
tables created before those columns existed, and drops the ones in ``DROPPED_COLUMNS``.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event, inspect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str) -> Engine:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


@lru_cache
def get_engine() -> Engine:
    return make_engine(get_settings().database_url)


def init_db(engine: Engine | None = None) -> None:
    """Create all tables that do not exist yet."""
    import app.models  # noqa: F401 - register the models on Base.metadata

    engine = engine or get_engine()
    Base.metadata.create_all(engine)
    _execute(engine, _missing_columns(engine))
    _execute(engine, _obsolete_columns(engine))


ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "applications": {
        "start_date": "DATE",
        "salary_override": "JSON",
        "work_mode_override": "VARCHAR(16)",
        "cv_overrides": "JSON",
    },
    "generated_cvs": {
        "overrides": "JSON",
    },
    "work_history": {
        "application_id": "INTEGER REFERENCES applications(id) ON DELETE SET NULL",
        "prefill_state": "VARCHAR(16)",
        "kind": "VARCHAR(16) NOT NULL DEFAULT 'job'",
        "transition": "VARCHAR(16)",
        "journal_context": "TEXT",
        "journal_tech": "JSON",
        "journal_hash": "VARCHAR(64)",
        "journal_failed_hash": "VARCHAR(64)",
        "journal_warnings": "JSON",
    },
    "application_events": {
        "source": "VARCHAR(16) NOT NULL DEFAULT 'manual'",
        "source_ref": "VARCHAR(128)",
        "stage_entry": "BOOLEAN NOT NULL DEFAULT 0",
    },
    "job_parse_results": {
        "interview_steps": "JSON",
        "technologies": "JSON",
        "salary": "JSON",
        "work_mode": "VARCHAR(16)",
    },
    "candidate_details": {
        "photo": "TEXT NOT NULL DEFAULT ''",
    },
    "job_evaluations": {
        "explanation": "TEXT",
    },
    "gmail_monitor_settings": {
        "interview_label": "VARCHAR(128) NOT NULL DEFAULT 'interview-steps-registered'",
    },
}
"""Columns added to tables after they were first created: ``create_all`` only creates
missing tables, so these are added to existing databases with ``ALTER TABLE``."""


def _missing_columns(engine: Engine) -> list[str]:
    inspector = inspect(engine)
    statements = []
    for table, columns in ADDED_COLUMNS.items():
        existing = {column["name"] for column in inspector.get_columns(table)}
        statements += [
            f"ALTER TABLE {table} ADD COLUMN {name} {ddl}" for name, ddl in columns.items() if name not in existing
        ]
    return statements


DROPPED_COLUMNS: dict[str, list[str]] = {
    "candidate_details": ["education", "certifications", "consent_text"],
    "gmail_monitor_settings": ["email"],
}
"""Columns no longer in the models; dropped from existing databases with ``ALTER TABLE``.
Education and certifications moved to ``work_history`` (``kind``); the Gmail monitor uses
the e-mail of the personal details; the consent clause is in ``cv_settings``."""


def _obsolete_columns(engine: Engine) -> list[str]:
    inspector = inspect(engine)
    statements = []
    for table, columns in DROPPED_COLUMNS.items():
        if not inspector.has_table(table):
            continue
        existing = {column["name"] for column in inspector.get_columns(table)}
        statements += [f"ALTER TABLE {table} DROP COLUMN {name}" for name in columns if name in existing]
    return statements


def _execute(engine: Engine, statements: list[str]) -> None:
    if statements:
        with engine.begin() as conn:
            for statement in statements:
                conn.exec_driver_sql(statement)


def session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=engine or get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency. Tests override this with a temporary SQLite database."""
    with session_factory()() as session:
        yield session
