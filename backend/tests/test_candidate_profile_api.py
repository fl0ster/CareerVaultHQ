import json
BASE = "/api/candidate-profile"


def test_latest_is_null_when_empty(client):
    res = client.get(f"{BASE}/latest")
    assert res.status_code == 200
    assert res.json() is None

# --- POST /create ----------------------------------------------------------------------

import httpx
from sqlalchemy import select

from app.config import Settings, get_settings
from app.db import get_session
from app.main import app
from app.models import OpenRouterCall
from app.services.openrouter import OpenRouterService, get_openrouter

WORK_HISTORY = "/api/work-history"


def _mock_openrouter(client, content, requests_seen):
    def handle(request: httpx.Request) -> httpx.Response:
        requests_seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "gen-1",
                "model": "test/model",
                "choices": [{"message": {"role": "assistant", "content": content}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0.001},
            },
        )

    settings = Settings(openrouter_api_key="sk-test", cors_origins=[])
    transport = httpx.MockTransport(handle)
    override = app.dependency_overrides[get_session]

    def override_openrouter():
        for session in override():
            yield OpenRouterService(session, settings, transport=transport)

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_openrouter] = override_openrouter


def _add_entry(client, employer="Acme", role="Dev"):
    res = client.post(
        WORK_HISTORY,
        json={"date_start": "2020-01-01", "employer": employer, "role": role, "tech": ["python"]},
    )
    assert res.status_code == 201
    return res.json()


def test_generate_requires_work_history(client):
    res = client.post(f"{BASE}/generate")
    assert res.status_code == 400
    assert res.json()["detail"] == "missing work history"


def test_generate_generates_profile_from_work_history(client, db_session):
    _add_entry(client)
    seen = []
    _mock_openrouter(client, "  A seasoned Python developer.  ", seen)

    res = client.post(f"{BASE}/generate")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["content"] == "A seasoned Python developer."
    assert body["work_history_id"]
    assert client.get(f"{BASE}/latest").json()["id"] == body["id"]

    # The exported work history was sent as context.
    assert len(seen) == 1
    prompt = seen[0]["messages"][-1]["content"]
    assert "Acme" in prompt and "Jan 2020" in prompt and "python" in prompt
    call = db_session.scalars(select(OpenRouterCall)).one()
    assert call.source == "candidate_profile.create"


def test_generate_does_not_reject_when_already_generated(client):
    _add_entry(client)
    seen = []
    _mock_openrouter(client, "profile", seen)

    assert client.post(f"{BASE}/generate").status_code == 201
    res = client.post(f"{BASE}/generate")
    assert res.status_code == 201
    assert len(seen) == 2


def test_generate_again_after_work_history_changes(client):
    entry = _add_entry(client)
    seen = []
    _mock_openrouter(client, "profile", seen)
    first = client.post(f"{BASE}/generate").json()

    res = client.patch(f"{WORK_HISTORY}/{entry['id']}", json={"role": "Lead"})
    assert res.status_code == 200
    second = client.post(f"{BASE}/generate")
    assert second.status_code == 201
    assert second.json()["work_history_id"] != first["work_history_id"]
    assert len(seen) == 2
