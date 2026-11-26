"""``/api/work-history/{role_id}/journal``: logging notes, queuing their regeneration on the
worker and reading what was built from them."""

import json
from datetime import date, timedelta

import httpx
import pytest

from app.config import Settings, get_settings
from app.main import app
from app.models import WorkJournalEntry
from app.services.openrouter import OpenRouterService
from app.tasks.work_history import journal as journal_task

BASE = "/api/work-history"
TODAY = date.today()


@pytest.fixture
def llm(client, monkeypatch):
    """An API key for the routes and a mocked OpenRouter for the worker task: every generated
    text is faithful unless ``state["status"]`` fails the calls. ``state["calls"]`` has the
    kinds of the calls made."""
    state = {"calls": [], "status": 200}

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if state["status"] != 200:
            return httpx.Response(state["status"], json={"error": {"message": "boom"}})
        if request.url.path.endswith("/decisions"):
            state["calls"].append("faithful")
            return httpx.Response(
                200, json={"id": "d", "model": "jev", "answers": {"is_faithful": {"type": "noul", "noul": 0.9}}}
            )
        if "work-journal notes" in body["messages"][-1]["content"]:
            state["calls"].append("month")
            content = json.dumps({"summary": "Shipped the API.", "accomplishments": ["Shipped the API"], "tech": ["Python"]})
        else:
            state["calls"].append("context")
            content = "Built the API in Python."
        return httpx.Response(
            200, json={"id": "c", "model": "m", "choices": [{"message": {"role": "assistant", "content": content}}]}
        )

    keyed = app.dependency_overrides[get_settings]().model_copy(update={"openrouter_api_key": "sk-test"})
    app.dependency_overrides[get_settings] = lambda: keyed
    settings = Settings(openrouter_api_key="sk-test", cors_origins=[])
    monkeypatch.setattr(
        journal_task,
        "OpenRouterService",
        lambda session, *_a, **_k: OpenRouterService(session, settings, transport=httpx.MockTransport(handle)),
    )
    return state


def _run_refresh(fake_queue, role_id: int) -> None:
    """What the worker does with the queued job: run it, then the job is finished."""
    job = fake_queue.fetch_job(journal_task.refresh_job_id(role_id))
    assert job is not None
    journal_task.refresh_work_journal(role_id)
    job.delete()


def _role(client, **fields) -> dict:
    payload = {"kind": "job", "date_start": "2024-01-01", "employer": "Acme", "role": "Engineer", "tech": []}
    response = client.post(BASE, json=payload | fields)
    assert response.status_code == 201, response.text
    return response.json()


def test_log_read_edit_and_delete_notes(client):
    role = _role(client)
    url = f"{BASE}/{role['id']}/journal"

    first = client.post(url, json={"body": "  Wrote the importer in Python.  "})
    assert first.status_code == 201, first.text
    assert first.json()["body"] == "Wrote the importer in Python."
    assert first.json()["logged_on"] == TODAY.isoformat()
    earlier = (TODAY - timedelta(days=40)).isoformat()
    second = client.post(url, json={"body": "Reviewed the schema.", "logged_on": earlier}).json()

    journal = client.get(url).json()
    assert [e["id"] for e in journal["entries"]] == [first.json()["id"], second["id"]]
    assert len(journal["months"]) == 2
    assert all(m["stale"] and m["summary"] is None for m in journal["months"])
    assert journal["months"][0]["month"] > journal["months"][1]["month"]
    assert journal["stale"] and journal["journal_context"] is None and journal["warnings"] == []

    edited = client.patch(f"{url}/{second['id']}", json={"body": "Reviewed the DB schema."})
    assert edited.status_code == 200 and edited.json()["body"] == "Reviewed the DB schema."

    assert client.delete(f"{url}/{second['id']}").status_code == 204
    assert [e["id"] for e in client.get(url).json()["entries"]] == [first.json()["id"]]
    assert client.delete(f"{url}/{second['id']}").status_code == 404


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        ({"body": "   "}, "empty"),
        ({"body": "x", "logged_on": (TODAY + timedelta(days=1)).isoformat()}, "future"),
        ({"body": "x", "logged_on": "2023-12-31"}, "within the position"),
    ],
)
def test_invalid_notes_are_rejected(client, payload, detail):
    role = _role(client)
    response = client.post(f"{BASE}/{role['id']}/journal", json=payload)
    assert response.status_code == 422 and detail in response.text


def test_only_positions_have_a_journal(client):
    degree = _role(client, kind="education", employer="Uni", role="MSc")
    assert client.get(f"{BASE}/{degree['id']}/journal").status_code == 422
    assert client.get(f"{BASE}/9999/journal").status_code == 404


def test_a_note_of_another_role_is_not_found(client):
    one, other = _role(client), _role(client, employer="Other")
    note = client.post(f"{BASE}/{one['id']}/journal", json={"body": "Mine"}).json()
    assert client.patch(f"{BASE}/{other['id']}/journal/{note['id']}", json={"body": "x"}).status_code == 404


def test_deleting_the_role_deletes_its_journal(client, db_session):
    role = _role(client)
    client.post(f"{BASE}/{role['id']}/journal", json={"body": "Note"})
    assert client.delete(f"{BASE}/{role['id']}").status_code == 204
    assert db_session.query(WorkJournalEntry).count() == 0


def test_refresh_is_queued_on_the_worker_once_and_fills_the_journal(client, llm, fake_queue):
    role = _role(client)
    url = f"{BASE}/{role['id']}/journal"
    client.post(url, json={"body": "Shipped the API in Python."})

    queued = client.post(f"{url}/refresh")
    assert queued.status_code == 202, queued.text
    assert queued.json()["refreshing"] and queued.json()["stale"]
    # No LLM call in the request: the work waits on the queue, once per position.
    assert llm["calls"] == []
    assert client.post(f"{url}/refresh").status_code == 202
    assert fake_queue.job_ids == [journal_task.refresh_job_id(role["id"])]
    assert client.get(url).json()["refreshing"]

    _run_refresh(fake_queue, role["id"])
    assert llm["calls"] == ["month", "faithful", "context", "faithful"]

    journal = client.get(url).json()
    assert not journal["refreshing"] and not journal["stale"] and journal["warnings"] == []
    month = journal["months"][0]
    assert month["month"] == TODAY.replace(day=1).isoformat() and not month["stale"]
    assert (month["summary"], month["accomplishments"], month["tech"]) == (
        "Shipped the API.",
        ["Shipped the API"],
        ["Python"],
    )
    assert journal["journal_context"] == "Built the API in Python."
    assert not journal["context_overridden"]

    # Nothing stale: asking again queues nothing.
    assert not client.post(f"{url}/refresh").json()["refreshing"]
    assert fake_queue.job_ids == []

    entry = client.get(f"{BASE}/{role['id']}").json()
    assert entry["journal_context"] == "Built the API in Python." and entry["journal_tech"] == ["Python"]
    assert not entry["context"]
    assert entry["journal_count"] == 1 and not entry["journal_overdue"]


def test_the_warnings_of_the_last_refresh_are_kept(client, llm, fake_queue):
    role = _role(client)
    url = f"{BASE}/{role['id']}/journal"
    client.post(url, json={"body": "Note"})
    llm["status"] = 500
    client.post(f"{url}/refresh")
    _run_refresh(fake_queue, role["id"])

    journal = client.get(url).json()
    assert journal["stale"] and not journal["refreshing"]
    assert len(journal["warnings"]) == 1 and "could not be summarised" in journal["warnings"][0]

    # A new refresh starts without the old warnings.
    llm["status"] = 200
    assert client.post(f"{url}/refresh").json()["warnings"] == []
    _run_refresh(fake_queue, role["id"])
    assert client.get(url).json()["warnings"] == []


def test_refresh_without_an_api_key_is_503(client, fake_queue):
    role = _role(client)
    client.post(f"{BASE}/{role['id']}/journal", json={"body": "Note"})
    assert client.post(f"{BASE}/{role['id']}/journal/refresh").status_code == 503
    assert fake_queue.job_ids == []


def test_the_worker_reports_a_missing_api_key(client, monkeypatch):
    role = _role(client)
    client.post(f"{BASE}/{role['id']}/journal", json={"body": "Note"})
    unkeyed = Settings(openrouter_api_key="", cors_origins=[])
    monkeypatch.setattr(journal_task, "OpenRouterService", lambda session: OpenRouterService(session, unkeyed))
    assert journal_task.refresh_work_journal(role["id"])["warnings"] == [journal_task.NOT_CONFIGURED]
    assert client.get(f"{BASE}/{role['id']}/journal").json()["warnings"] == [journal_task.NOT_CONFIGURED]


def test_overdue_positions_in_the_list_and_the_menu(client):
    role = _role(client)
    ended = _role(client, employer="Old", date_end="2024-06-30")
    assert client.get("/api/nav/counts").json()["journal_overdue"] == 0  # just added

    # A note added today but dated eight days ago does not count as this week's update.
    eight_days_ago = (TODAY - timedelta(days=8)).isoformat()
    client.post(f"{BASE}/{role['id']}/journal", json={"body": "Backfilled", "logged_on": eight_days_ago})

    entries = {e["id"]: e for e in client.get(BASE).json()}
    assert entries[role["id"]]["journal_overdue"]
    assert entries[role["id"]]["last_journal_on"] == eight_days_ago
    assert not entries[ended["id"]]["journal_overdue"] and entries[ended["id"]]["journal_count"] == 0
    assert client.get("/api/nav/counts").json()["journal_overdue"] == 1

    client.post(f"{BASE}/{role['id']}/journal", json={"body": "Fresh note"})
    assert client.get(f"{BASE}/{role['id']}").json()["last_journal_on"] == TODAY.isoformat()
    assert client.get("/api/nav/counts").json()["journal_overdue"] == 0
