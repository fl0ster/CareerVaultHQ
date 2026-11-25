import json

import httpx
from sqlalchemy import select

from app.config import Settings, get_settings
from app.db import get_session
from app.main import app
from app.models import CandidateProfile, OpenRouterCall
from app.services.openrouter import OpenRouterService, get_openrouter

BASE = "/api/candidate-profile"
WORK_HISTORY = "/api/work-history"


def test_latest_is_null_when_empty(client):
    res = client.get(f"{BASE}/latest")
    assert res.status_code == 200
    assert res.json() is None


# --- lazy generation via GET /latest ---------------------------------------------------


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


def test_latest_without_work_history_returns_existing_profile(client, db_session):
    profile = CandidateProfile(content="Python dev")
    db_session.add(profile)
    db_session.commit()
    assert client.get(f"{BASE}/latest").json()["id"] == profile.id


def test_latest_generates_profile_lazily(client, db_session):
    _add_entry(client)
    seen = []
    _mock_openrouter(client, "  A seasoned Python developer.  ", seen)

    res = client.get(f"{BASE}/latest")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["content"] == "A seasoned Python developer."
    assert body["work_history_id"]

    # The exported work history was sent as context.
    assert len(seen) == 1
    prompt = seen[0]["messages"][-1]["content"]
    assert "Acme" in prompt and "Jan 2020" in prompt and "python" in prompt
    call = db_session.scalars(select(OpenRouterCall)).one()
    assert call.source == "candidate_profile.create"


def test_education_and_certificates_are_not_part_of_the_profile(client):
    _add_entry(client)
    seen = []
    _mock_openrouter(client, "profile", seen)
    first = client.get(f"{BASE}/latest").json()

    for kind, role in (("education", "MSc Physics"), ("certificate", "CKA")):
        res = client.post(WORK_HISTORY, json={"kind": kind, "date_start": "2019-01-01", "role": role})
        assert res.status_code == 201, res.text
    # the profile describes the work experience only: unchanged, so it is reused
    assert client.get(f"{BASE}/latest").json()["id"] == first["id"]
    assert len(seen) == 1
    assert "MSc Physics" not in seen[0]["messages"][-1]["content"]


def test_latest_reuses_profile_while_work_history_unchanged(client):
    _add_entry(client)
    seen = []
    _mock_openrouter(client, "profile", seen)

    first = client.get(f"{BASE}/latest").json()
    second = client.get(f"{BASE}/latest").json()
    assert first["id"] == second["id"]
    assert len(seen) == 1


def test_latest_regenerates_after_work_history_changes(client):
    entry = _add_entry(client)
    seen = []
    _mock_openrouter(client, "profile", seen)
    first = client.get(f"{BASE}/latest").json()

    res = client.patch(f"{WORK_HISTORY}/{entry['id']}", json={"role": "Lead"})
    assert res.status_code == 200
    second = client.get(f"{BASE}/latest").json()
    assert second["id"] != first["id"]
    assert second["work_history_id"] != first["work_history_id"]
    assert len(seen) == 2


def test_latest_regenerates_after_entry_deleted(client):
    _add_entry(client)
    other = _add_entry(client, employer="Initech")
    seen = []
    _mock_openrouter(client, "profile", seen)
    first = client.get(f"{BASE}/latest").json()

    assert client.delete(f"{WORK_HISTORY}/{other['id']}").status_code == 204
    assert client.get(f"{BASE}/latest").json()["id"] != first["id"]
    assert len(seen) == 2


def test_latest_returns_502_when_generation_fails(client):
    _add_entry(client)
    _mock_openrouter(client, "   ", [])

    res = client.get(f"{BASE}/latest")
    assert res.status_code == 502


# --- evaluation enqueued on generation -------------------------------------------------


def _evaluation_jobs(fake_queue):
    return [j for j in fake_queue.jobs if j.func_name.endswith("evaluate_pending_jobs")]


def test_lazy_generation_enqueues_evaluation_batch(client, fake_queue):
    _add_entry(client)
    _mock_openrouter(client, "A profile.", [])

    res = client.get(f"{BASE}/latest")
    assert res.status_code == 200

    jobs = _evaluation_jobs(fake_queue)
    assert len(jobs) == 1
    assert jobs[0].args == (Settings().evaluate_batch_size,)
    assert jobs[0].meta == {"candidate_profile_id": res.json()["id"]}

    # Reading the unchanged profile again enqueues nothing.
    client.get(f"{BASE}/latest")
    assert len(_evaluation_jobs(fake_queue)) == 1


def test_generation_succeeds_when_queue_is_down(client, fake_queue, monkeypatch):
    def boom(*args, **kwargs):
        raise ConnectionError("redis down")

    monkeypatch.setattr(fake_queue, "enqueue", boom)
    _add_entry(client)
    _mock_openrouter(client, "A profile.", [])

    res = client.get(f"{BASE}/latest")
    assert res.status_code == 200
    assert client.get(f"{BASE}/latest").json()["id"] == res.json()["id"]


def test_transition_is_sent_only_when_set(client, db_session):
    from app.services.candidate_profile import _work_history_payload

    _add_entry(client)
    before = _work_history_payload(db_session)
    assert "transition" not in before[0]  # unchanged shape (and hash) without promotions

    res = client.post(
        WORK_HISTORY,
        json={"date_start": "2023-01-01", "employer": "Acme", "role": "Lead", "transition": "promotion"},
    )
    assert res.status_code == 201
    db_session.expire_all()
    payload = _work_history_payload(db_session)
    assert payload[0]["transition"] == "promotion"
    assert payload[1]["date_end"] == "Dec 2022"  # the promotion ended the previous role
