import pytest
from fakeredis import FakeStrictRedis
from fastapi.testclient import TestClient
from rq import Queue

from app.config import Settings, get_settings
from app.db import get_engine, get_session, init_db, make_engine, session_factory
from app.main import app
from app.queue import get_queue


@pytest.fixture
def upload_root(tmp_path):
    return tmp_path / "uploads"


@pytest.fixture
def jobs_root(tmp_path):
    return tmp_path / "jobs"


@pytest.fixture
def fake_queue():
    # is_async=False would run jobs inline; keep them queued so tests exercise the API only.
    return Queue("latex", connection=FakeStrictRedis())


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
def client(upload_root, jobs_root, fake_queue, engine):
    settings = Settings(
        latex_upload_root=upload_root,
        latex_jobs_root=jobs_root,
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
