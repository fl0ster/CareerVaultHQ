"""``app.tasks.work_history.prefill``: filling in an accepted offer's work-history entry."""

import json
from datetime import UTC, date, datetime

import httpx
import pytest

from app.config import Settings
from app.models import (
    Application,
    ApplicationEvent,
    Company,
    Job,
    JobParseResult,
    WorkHistoryEntry,
)
from app.services.applications import accept_offer, status_by_key
from app.services.openrouter import OpenRouterService
from app.tasks.work_history.prefill import enqueue_prefill, parse_reply, prefill
from tests.conftest import ensure_source

REPLY = {
    "role": "Senior Backend Engineer",
    "location": "Warsaw, Poland",
    "tech": ["Python", "FastAPI", "python", " PostgreSQL "],
    "context": "Payments platform team. Owns the settlement services.",
}


@pytest.fixture
def llm(db_session):
    """OpenRouter mock replying with ``state["reply"]`` (a dict is sent as JSON) or failing
    with ``state["status"]``; prompts are kept in ``state["prompts"]``."""
    state = {"reply": REPLY, "status": 200, "prompts": []}

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        state["prompts"].append(body["messages"][-1]["content"])
        if state["status"] != 200:
            return httpx.Response(state["status"], json={"error": {"message": "boom"}})
        reply = state["reply"]
        content = reply if isinstance(reply, str) else json.dumps(reply)
        return httpx.Response(
            200,
            json={"id": "c", "model": "m", "choices": [{"message": {"role": "assistant", "content": content}}]},
        )

    settings = Settings(openrouter_api_key="sk-test", cors_origins=[])
    state["service"] = OpenRouterService(db_session, settings, transport=httpx.MockTransport(handle))
    return state


def _accepted(db_session) -> WorkHistoryEntry:
    interview, offer = status_by_key(db_session, "INTERVIEW"), status_by_key(db_session, "OFFER")
    status_by_key(db_session, "ACCEPTED")
    parsed = JobParseResult(
        job=Job(link="https://example.com/jobs/1", source=ensure_source(db_session)),
        title="Backend Engineer",
        description="We build payments in Warsaw. Python, FastAPI.",
        company=Company(name="Acme", normalized_name="acme", notes="Fintech, 200 people"),
        technologies=[{"name": "Python", "key": "python"}],
    )
    application = Application(job_parse_result=parsed, notes="Great team")
    application.events.append(
        ApplicationEvent(
            status=interview,
            title="Tech interview",
            note="system design",
            occurred_at=datetime(2026, 10, 1, tzinfo=UTC),
        )
    )
    application.events.append(ApplicationEvent(status=offer, occurred_at=datetime(2026, 10, 10, tzinfo=UTC)))
    db_session.add(application)
    db_session.flush()
    entry = accept_offer(db_session, application, date(2027, 1, 4))
    db_session.commit()
    return entry


def test_prefill_fills_the_entry_from_the_application(db_session, llm):
    entry = _accepted(db_session)
    assert (entry.role, entry.tech, entry.prefill_state) == ("Backend Engineer", ["Python"], "queued")

    entry = prefill(db_session, entry, llm["service"])
    assert entry.prefill_state == "done"
    assert entry.role == "Senior Backend Engineer"
    assert entry.location == "Warsaw, Poland"
    assert entry.tech == ["Python", "FastAPI", "PostgreSQL"]
    assert entry.context == REPLY["context"]
    assert (entry.employer, entry.date_start) == ("Acme", date(2027, 1, 4))

    prompt = llm["prompts"][0]
    for text in ("We build payments", "Fintech, 200 people", "Great team", "Tech interview", "system design", "Offer"):
        assert text in prompt


def test_prefill_keeps_what_the_user_changed(db_session, llm):
    entry = _accepted(db_session)
    entry.role, entry.location, entry.tech, entry.context = "Staff Engineer", "Remote", ["Go"], "Mine"
    db_session.commit()

    entry = prefill(db_session, entry, llm["service"])
    assert (entry.role, entry.location, entry.tech, entry.context) == ("Staff Engineer", "Remote", ["Go"], "Mine")
    assert entry.prefill_state == "done"


def test_prefill_failure_leaves_the_entry_usable(db_session, llm):
    entry = _accepted(db_session)
    llm["status"] = 500
    entry = prefill(db_session, entry, llm["service"])
    assert entry.prefill_state == "failed"
    assert (entry.role, entry.location, entry.context) == ("Backend Engineer", None, None)


def test_prefill_without_an_api_key_fails(db_session):
    entry = _accepted(db_session)
    service = OpenRouterService(db_session, Settings(openrouter_api_key="", cors_origins=[]))
    assert prefill(db_session, entry, service).prefill_state == "failed"


def test_unreadable_reply_changes_nothing(db_session, llm):
    entry = _accepted(db_session)
    llm["reply"] = "sorry, no"
    entry = prefill(db_session, entry, llm["service"])
    assert entry.prefill_state == "done"
    assert (entry.role, entry.location, entry.tech) == ("Backend Engineer", None, ["Python"])


def test_parse_reply_cleans_values():
    data = parse_reply('```json\n{"role": "  Dev  ", "location": "null", "tech": "Python", "context": 5}\n```')
    assert data == {"role": "Dev", "location": None, "tech": [], "context": None}


def test_enqueue_failure_marks_the_entry_failed(db_session):
    entry = _accepted(db_session)

    class DownQueue:
        def enqueue(self, *args, **kwargs):
            raise ConnectionError("redis down")

    enqueue_prefill(db_session, DownQueue(), entry)
    assert db_session.get(WorkHistoryEntry, entry.id).prefill_state == "failed"
