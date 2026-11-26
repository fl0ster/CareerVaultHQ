"""``/api/work-history/{role_id}/journal``: logging notes and reading what was built from them."""

import json
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

import httpx
import pytest
from fastapi import Depends
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_session
from app.main import app
from app.models import WorkJournalEntry
from app.services.openrouter import OpenRouterService, get_openrouter

BASE = "/api/work-history"
TODAY = date.today()


@pytest.fixture
def llm(client):
    """Mocked OpenRouter behind ``get_openrouter``: every generated text is faithful. Returns
    the kinds of the calls made."""
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path.endswith("/decisions"):
            calls.append("faithful")
            return httpx.Response(
                200, json={"id": "d", "model": "jev", "answers": {"is_faithful": {"type": "noul", "noul": 0.9}}}
            )
        if "work-journal notes" in body["messages"][-1]["content"]:
            calls.append("month")
            content = json.dumps({"summary": "Shipped the API.", "accomplishments": ["Shipped the API"], "tech": ["Python"]})
        else:
            calls.append("context")
            content = "Built the API in Python."
        return httpx.Response(
            200, json={"id": "c", "model": "m", "choices": [{"message": {"role": "assistant", "content": content}}]}
        )

    settings = Settings(openrouter_api_key="sk-test", cors_origins=[])

    def override(session: Annotated[Session, Depends(get_session)]):
        yield OpenRouterService(session, settings, transport=httpx.MockTransport(handle))

    app.dependency_overrides[get_openrouter] = override
    return calls


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


def test_refresh_generates_lazily_and_feeds_the_role(client, llm):
    role = _role(client)
    url = f"{BASE}/{role['id']}/journal"
    client.post(url, json={"body": "Shipped the API in Python."})

    refreshed = client.post(f"{url}/refresh")
    assert refreshed.status_code == 200, refreshed.text
    journal = refreshed.json()
    assert llm == ["month", "faithful", "context", "faithful"]
    assert not journal["stale"] and journal["warnings"] == []
    month = journal["months"][0]
    assert month["month"] == TODAY.replace(day=1).isoformat() and not month["stale"]
    assert (month["summary"], month["accomplishments"], month["tech"]) == (
        "Shipped the API.",
        ["Shipped the API"],
        ["Python"],
    )
    assert journal["journal_context"] == "Built the API in Python."
    assert not journal["context_overridden"]

    # Cached: a second refresh makes no call.
    client.post(f"{url}/refresh")
    assert len(llm) == 4

    entry = client.get(f"{BASE}/{role['id']}").json()
    assert entry["journal_context"] == "Built the API in Python." and entry["journal_tech"] == ["Python"]
    assert not entry["context"]
    assert entry["journal_count"] == 1 and not entry["journal_overdue"]


def test_refresh_without_an_api_key_is_503(client):
    role = _role(client)
    client.post(f"{BASE}/{role['id']}/journal", json={"body": "Note"})
    assert client.post(f"{BASE}/{role['id']}/journal/refresh").status_code == 503


def test_overdue_positions_in_the_list_and_the_menu(client, db_session):
    role = _role(client)
    ended = _role(client, employer="Old", date_end="2024-06-30")
    assert client.get("/api/nav/counts").json()["journal_overdue"] == 0  # just added

    note = client.post(f"{BASE}/{role['id']}/journal", json={"body": "Note"}).json()
    row = db_session.get(WorkJournalEntry, note["id"])
    row.created_at = datetime.now(UTC) - timedelta(days=8)
    db_session.commit()

    entries = {e["id"]: e for e in client.get(BASE).json()}
    assert entries[role["id"]]["journal_overdue"] and entries[role["id"]]["last_journal_at"]
    assert not entries[ended["id"]]["journal_overdue"] and entries[ended["id"]]["journal_count"] == 0
    assert client.get("/api/nav/counts").json()["journal_overdue"] == 1

    client.post(f"{BASE}/{role['id']}/journal", json={"body": "Fresh note"})
    assert client.get("/api/nav/counts").json()["journal_overdue"] == 0
