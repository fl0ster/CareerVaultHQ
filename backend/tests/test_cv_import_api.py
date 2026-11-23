"""``/api/cv-import``: upload validation, queueing and the job status / result endpoint."""

import json

import httpx
import pytest
from fakeredis import FakeStrictRedis
from rq import Queue
from rq.job import Job

import app.tasks.cv_import as cv_import_task
from app.config import Settings, get_settings
from app.main import app
from app.queue import get_queue
from app.services.openrouter import OpenRouterService
from tests.cv_pdf import make_pdf
from tests.test_cv_import_task import reply


def upload(client, data: bytes, name: str = "cv.pdf"):
    return client.post("/api/cv-import", files={"file": (name, data, "application/pdf")})


def test_upload_queues_an_import(client, fake_queue, cv_import_root):
    response = upload(client, make_pdf())

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["status_url"].endswith(f"/api/cv-import/jobs/{body['job_id']}")

    job = fake_queue.fetch_job(body["job_id"])
    assert job.func_name == "app.tasks.cv_import.import_cv"
    [stored] = cv_import_root.glob("*/cv.pdf")
    assert job.args == (str(stored),)
    assert stored.read_bytes()[:5] == b"%PDF-"

    status = client.get(f"/api/cv-import/jobs/{body['job_id']}").json()
    assert status["status"] == "queued"
    assert status["filename"] == "cv.pdf"
    assert status["result"] is None and status["error"] is None


@pytest.mark.parametrize(
    ("data", "code"),
    [(b"", 400), (b"%PDF-" + b"x" * 64, 413), (b"<html>not a pdf</html>", 415)],
    ids=["empty", "too-large", "not-a-pdf"],
)
def test_bad_uploads_are_rejected(client, fake_queue, cv_import_root, data, code):
    settings = app.dependency_overrides[get_settings]()
    small = settings.model_copy(update={"cv_import_max_upload_bytes": 32})
    app.dependency_overrides[get_settings] = lambda: small

    response = upload(client, data)
    assert response.status_code == code
    assert fake_queue.count == 0
    assert not list(cv_import_root.glob("*/cv.pdf"))


def test_missing_file_is_rejected(client):
    assert client.post("/api/cv-import").status_code == 422


def test_unknown_or_foreign_job_is_404(client, fake_queue):
    assert client.get("/api/cv-import/jobs/nope").status_code == 404
    other = fake_queue.enqueue(print, "x", meta={"kind": "something-else"})
    assert client.get(f"/api/cv-import/jobs/{other.id}").status_code == 404


@pytest.fixture
def sync_queue(client):
    """Runs the enqueued import inline so the status endpoint can be checked end to end."""
    queue = Queue("jobs", is_async=False, connection=FakeStrictRedis())
    app.dependency_overrides[get_queue] = lambda: queue
    return queue


@pytest.fixture
def worker_env(monkeypatch, db_session):
    settings = Settings(openrouter_api_key="sk-test", cors_origins=[], cv_import_min_text_chars=50)
    state = {"reply": reply()}

    def handle(request: httpx.Request) -> httpx.Response:
        content = json.dumps(state["reply"])
        return httpx.Response(200, json={"id": "c", "model": "m", "choices": [{"message": {"content": content}}]})

    service = OpenRouterService(db_session, settings, transport=httpx.MockTransport(handle))
    monkeypatch.setattr(cv_import_task, "get_settings", lambda: settings)
    monkeypatch.setattr(cv_import_task, "OpenRouterService", lambda session, _settings: service)
    return state


def test_finished_import_returns_the_result(client, sync_queue, worker_env, cv_import_root):
    job_id = upload(client, make_pdf()).json()["job_id"]

    status = client.get(f"/api/cv-import/jobs/{job_id}").json()

    assert status["status"] == "finished"
    assert status["error"] is None
    result = status["result"]
    assert result["candidate_details"]["linkedin"] == "linkedin.com/in/jane-doe"
    assert [e["employer"] for e in result["work_history"]] == ["Acme Corp", "Globex"]
    assert not list(cv_import_root.glob("*/cv.pdf"))  # the worker removed the upload

    # The result is accepted as-is by the endpoints that save it.
    assert client.put("/api/candidate-details", json=result["candidate_details"]).status_code == 200
    saved = client.post("/api/work-history/json", json=result["work_history"])
    assert saved.status_code in (200, 201)
    assert len(client.get("/api/work-history").json()) == 2


def test_failed_import_reports_the_reason(client, sync_queue, worker_env):
    job_id = upload(client, make_pdf([])).json()["job_id"]

    status = client.get(f"/api/cv-import/jobs/{job_id}").json()

    assert status["status"] == "failed"
    assert status["result"] is None
    assert status["error"] == "the PDF has no text layer (is it a scan?); upload a text-based PDF"
    assert Job.fetch(job_id, connection=sync_queue.connection).is_failed
