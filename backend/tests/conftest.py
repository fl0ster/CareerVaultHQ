import pytest
from fakeredis import FakeStrictRedis
from fastapi.testclient import TestClient
from rq import Queue

from app.config import Settings, get_settings
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
def client(upload_root, jobs_root, fake_queue):
    settings = Settings(
        latex_upload_root=upload_root, latex_jobs_root=jobs_root, cors_origins=[]
    )

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_queue] = lambda: fake_queue
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
