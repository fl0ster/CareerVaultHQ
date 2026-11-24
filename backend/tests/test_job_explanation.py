"""``POST /api/jobs/{job_id}/explanation``: an LLM-written reason for a current score,
stored with the evaluation."""

import json

import httpx
import pytest

from app.config import Settings
from app.db import session_factory
from app.main import app
from app.models import JobEvaluation
from app.services.openrouter import OpenRouterService, get_openrouter
from tests.test_jobs_api import _seed_outdated


@pytest.fixture
def explainer(client, engine):
    """``client`` with the OpenRouter dependency answering every chat call with
    ``state["reply"]`` (or failing with ``state["status"]``), recording the request bodies."""
    state = {"reply": "Your Python matches.  You lack Kubernetes.", "status": 200, "requests": []}

    def handle(request: httpx.Request) -> httpx.Response:
        state["requests"].append(json.loads(request.content))
        if state["status"] != 200:
            return httpx.Response(state["status"], json={"error": {"message": "boom"}})
        return httpx.Response(
            200,
            json={"model": "m", "choices": [{"message": {"content": state["reply"]}}], "usage": {"cost": 0.001}},
        )

    settings = Settings(openrouter_api_key="test-key", database_url=str(engine.url))

    def override():
        with session_factory(engine)() as session:
            yield OpenRouterService(session, settings, transport=httpx.MockTransport(handle))

    app.dependency_overrides[get_openrouter] = override
    return state


def test_explanation_is_generated_once_and_stored_with_the_evaluation(client, db_session, explainer):
    first, _, new = _seed_outdated(db_session)

    res = client.post(f"/api/jobs/{first.job_id}/explanation")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["explanation"] == "Your Python matches. You lack Kubernetes."
    (request,) = explainer["requests"]
    prompt = request["messages"][-1]["content"]
    assert "Title 0" in prompt and "Desc 0" in prompt and new.content in prompt

    stored = db_session.get(JobEvaluation, data["evaluation_id"])
    db_session.refresh(stored)
    assert stored.candidate_profile_id == new.id
    assert stored.explanation == data["explanation"]

    # Answered from the stored text: no second call.
    assert client.post(f"/api/jobs/{first.job_id}/explanation").json() == data
    assert len(explainer["requests"]) == 1


def test_explanation_refused_for_outdated_or_unknown_jobs(client, db_session, explainer):
    _, last, _ = _seed_outdated(db_session)

    assert client.post(f"/api/jobs/{last.job_id}/explanation").status_code == 409
    assert client.post("/api/jobs/99999/explanation").status_code == 404
    assert explainer["requests"] == []


def test_failed_explanation_is_not_stored(client, db_session, explainer):
    first, _, _ = _seed_outdated(db_session)
    explainer["status"] = 500

    assert client.post(f"/api/jobs/{first.job_id}/explanation").status_code == 502
    explainer["status"] = 200
    assert client.post(f"/api/jobs/{first.job_id}/explanation").status_code == 200
    assert len(explainer["requests"]) == 2
