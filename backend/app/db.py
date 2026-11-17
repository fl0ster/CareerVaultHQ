"""SQLAlchemy engine / session shared by the API and the workers.

The schema is created with ``init_db()`` (``Base.metadata.create_all``) at API and
worker startup; there is no Alembic migration history yet. ``create_all`` never alters an
existing table, so ``init_db`` also adds model columns missing from existing tables
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
