import pytest
from fakeredis import FakeStrictRedis
from fastapi.testclient import TestClient
from rq import Queue
from sqlalchemy import select

from app.config import Settings, get_settings
from app.db import get_engine, get_session, init_db, make_engine, session_factory
from app.llm_calls import load_model_overrides
from app.main import app
from app.models import ScrapeSource
from app.queue import get_queue


def ensure_source(session, key: str = "skillshot", **fields) -> ScrapeSource:
    """The ``scrape_sources`` row for ``key``, created (and flushed) if missing. Tests that
    build ``Job`` rows by hand need one because ``jobs.source_id`` is a foreign key."""
    row = session.scalar(select(ScrapeSource).where(ScrapeSource.key == key))
    if row is None:
        row = ScrapeSource(key=key, name=key.title(), url=f"https://{key}.example/jobs", **fields)
        session.add(row)
        session.flush()
    return row


@pytest.fixture(autouse=True)
def no_model_overrides(tmp_path, monkeypatch):
    """Ignore a developer's local ``llm_models.toml``: every test sees the defaults from
    ``app.llm_calls`` unless it writes its own override file."""
    monkeypatch.setenv("OPENROUTER_MODELS_FILE", str(tmp_path / "no-llm-models.toml"))
    get_settings.cache_clear()
    load_model_overrides.cache_clear()
    yield
    get_settings.cache_clear()
    load_model_overrides.cache_clear()


@pytest.fixture
def upload_root(tmp_path):
    return tmp_path / "uploads"


@pytest.fixture
def jobs_root(tmp_path):
    return tmp_path / "jobs"


@pytest.fixture
def cv_root(tmp_path):
    return tmp_path / "cv"


@pytest.fixture
def cv_import_root(tmp_path):
    return tmp_path / "cv_import"


@pytest.fixture
def fake_queue():
    # is_async=False would run jobs inline; keep them queued so tests exercise the API only.
    return Queue("jobs", connection=FakeStrictRedis())


@pytest.fixture
def engine(tmp_path, monkeypatch):
    """Temporary SQLite database; ``app.db.get_engine`` is redirected to it."""
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    monkeypatch.setattr("app.db.get_engine", lambda: engine)
    return engine


@pytest.fixture
def db_session(engine):
    with session_factory(engine)() as session:
        yield session


@pytest.fixture
def client(upload_root, jobs_root, cv_root, cv_import_root, fake_queue, engine):
    settings = Settings(
        latex_upload_root=upload_root,
        latex_jobs_root=jobs_root,
        cv_root=cv_root,
        cv_import_upload_root=cv_import_root,
        cors_origins=[],
        database_url=str(engine.url),
    )

    def override_session():
        with session_factory(engine)() as session:
            yield session

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_queue] = lambda: fake_queue
    app.dependency_overrides[get_engine] = lambda: engine
    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
