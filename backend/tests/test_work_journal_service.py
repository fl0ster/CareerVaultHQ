"""``app.services.work_journal``: lazy, truthful summaries of a position's work journal."""

import json
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from app.config import Settings
from app.models import WorkHistoryEntry, WorkJournalEntry, WorkJournalMonth
from app.services import work_journal
from app.services.candidate_profile import _work_history_payload
from app.services.openrouter import OpenRouterNotConfigured, OpenRouterService
from app.tasks.cv.generate import load_roles

MONTH_REPLY = {
    "summary": "Built the payments retry queue in Python.",
    "accomplishments": ["Shipped the retry queue", "  "],
    "tech": ["Python", "Kafka", "python"],
}
CONTEXT_REPLY = "Built the payments retry queue in Python and Redis."


@pytest.fixture
def llm(db_session):
    """OpenRouter mock. Month summaries reply with ``state["month"]``, role descriptions with
    ``state["context"]``; faithfulness answers pop from ``state["faithful"]`` (0.9 once empty).
    ``state["calls"]`` records ``(kind, prompt)``; ``state["status"]`` != 200 fails every call."""
    state = {"month": MONTH_REPLY, "context": CONTEXT_REPLY, "faithful": [], "calls": [], "status": 200}

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if state["status"] != 200:
            return httpx.Response(state["status"], json={"error": {"message": "boom"}})
        if request.url.path.endswith("/decisions"):
            state["calls"].append(("faithful", body["state"]))
            noul = state["faithful"].pop(0) if state["faithful"] else 0.9
            return httpx.Response(
                200, json={"id": "d", "model": "jev", "answers": {"is_faithful": {"type": "noul", "noul": noul}}}
            )
        user = body["messages"][-1]["content"]
        kind = "month" if "work-journal notes" in user else "context"
        state["calls"].append((kind, user))
        reply = state[kind]
        content = reply if isinstance(reply, str) else json.dumps(reply)
        return httpx.Response(
            200, json={"id": "c", "model": "m", "choices": [{"message": {"role": "assistant", "content": content}}]}
        )

    settings = Settings(openrouter_api_key="sk-test", cors_origins=[])
    state["service"] = OpenRouterService(db_session, settings, transport=httpx.MockTransport(handle))
    return state


def _role(db_session, **fields) -> WorkHistoryEntry:
    values = {"kind": "job", "date_start": date(2024, 1, 1), "employer": "Acme", "role": "Engineer", "tech": []}
    role = WorkHistoryEntry(**(values | fields))
    db_session.add(role)
    db_session.commit()
    return role


def _note(db_session, role, day: date, body: str) -> WorkJournalEntry:
    note = WorkJournalEntry(work_history_id=role.id, logged_on=day, body=body)
    db_session.add(note)
    db_session.commit()
    db_session.refresh(role)
    return note


def _kinds(llm) -> list[str]:
    return [kind for kind, _ in llm["calls"]]


def test_a_role_without_a_journal_is_never_stale(db_session):
    assert not work_journal.is_stale(_role(db_session))


def test_refresh_summarises_each_month_then_builds_the_description(db_session, llm):
    role = _role(db_session)
    _note(db_session, role, date(2026, 10, 3), "Started the retry queue in Python with Kafka.")
    _note(db_session, role, date(2026, 11, 2), "Finished the retry queue; Python and Redis.")
    assert work_journal.stale_months(role) == [date(2026, 10, 1), date(2026, 11, 1)]

    assert work_journal.refresh_journal(db_session, role, llm["service"]) == []

    assert _kinds(llm) == ["month", "faithful", "month", "faithful", "context", "faithful"]
    october, november = sorted(role.journal_months, key=lambda m: m.month)
    assert october.summary == MONTH_REPLY["summary"]
    assert october.accomplishments == ["Shipped the retry queue"]
    assert october.tech == ["Python", "Kafka"]
    # "Kafka" is not in November's notes: a technology the notes do not name is dropped.
    assert november.tech == ["Python"]
    assert role.journal_context == CONTEXT_REPLY
    assert role.journal_tech == ["Python", "Kafka"]
    assert not work_journal.is_stale(role)
    # The month prompt carries the notes, dated.
    assert "- 2026-10-03: Started the retry queue" in llm["calls"][0][1]


def test_only_stale_months_are_regenerated(db_session, llm):
    role = _role(db_session)
    _note(db_session, role, date(2026, 10, 3), "Python work.")
    _note(db_session, role, date(2026, 11, 2), "More Python work.")
    work_journal.refresh_journal(db_session, role, llm["service"])
    llm["calls"].clear()

    # Nothing changed: no call at all.
    work_journal.refresh_journal(db_session, role, llm["service"])
    assert llm["calls"] == []

    _note(db_session, role, date(2026, 11, 20), "Python again.")
    assert work_journal.stale_months(role) == [date(2026, 11, 1)]
    llm["month"] = MONTH_REPLY | {"summary": "Different words."}
    work_journal.refresh_journal(db_session, role, llm["service"])
    assert _kinds(llm) == ["month", "faithful", "context", "faithful"]


def test_unchanged_summaries_keep_the_description(db_session, llm):
    role = _role(db_session)
    _note(db_session, role, date(2026, 11, 2), "Python work.")
    work_journal.refresh_journal(db_session, role, llm["service"])
    _note(db_session, role, date(2026, 11, 3), "More Python.")
    llm["calls"].clear()
    # Same month summary as before: the description is not rebuilt.
    work_journal.refresh_journal(db_session, role, llm["service"])
    assert _kinds(llm) == ["month", "faithful"]


def test_an_unfaithful_summary_is_retried_then_the_previous_one_kept(db_session, llm):
    role = _role(db_session)
    _note(db_session, role, date(2026, 11, 2), "Python work.")
    work_journal.refresh_journal(db_session, role, llm["service"])
    previous = role.journal_months[0].summary

    _note(db_session, role, date(2026, 11, 5), "Helped with a Python fix.")
    llm["calls"].clear()
    llm["month"] = MONTH_REPLY | {"summary": "Single-handedly cut costs by 90%."}
    llm["faithful"] = [0.1, 0.2]
    warnings = work_journal.refresh_journal(db_session, role, llm["service"])

    assert _kinds(llm) == ["month", "faithful", "month", "faithful"]
    assert len(warnings) == 1 and "truthfulness" in warnings[0] and "previous one is kept" in warnings[0]
    assert role.journal_months[0].summary == previous
    assert work_journal.is_stale(role)


def test_an_unfaithful_retry_that_passes_is_used(db_session, llm):
    role = _role(db_session)
    _note(db_session, role, date(2026, 11, 2), "Python work.")
    llm["faithful"] = [0.1]
    assert work_journal.refresh_journal(db_session, role, llm["service"]) == []
    assert _kinds(llm) == ["month", "faithful", "month", "faithful", "context", "faithful"]
    assert role.journal_months[0].summary == MONTH_REPLY["summary"]


def test_an_unfaithful_description_is_not_saved_nor_retried_until_the_summaries_change(db_session, llm):
    role = _role(db_session)
    _note(db_session, role, date(2026, 11, 2), "Python work.")
    llm["faithful"] = [0.9, 0.1, 0.1]
    warnings = work_journal.refresh_journal(db_session, role, llm["service"])
    assert warnings == [
        "No description built from your journal passed the truthfulness check; "
        "it will be tried again once your notes change."
    ]
    assert role.journal_context is None and role.journal_hash is None
    assert role.journal_failed_hash == work_journal.months_hash(role.journal_months)
    # The technologies need no LLM, so they are saved anyway.
    assert role.journal_tech == ["Python"]

    # Nothing changed: not stale, and a refresh (e.g. by a CV generation) makes no call.
    assert not work_journal.is_stale(role)
    llm["calls"].clear()
    assert work_journal.refresh_journal(db_session, role, llm["service"]) == []
    assert llm["calls"] == []

    # New notes that change the month's summary: the description is tried again.
    _note(db_session, role, date(2026, 11, 9), "More Python work.")
    llm["month"] = MONTH_REPLY | {"summary": "Built more of the queue in Python."}
    assert work_journal.refresh_journal(db_session, role, llm["service"]) == []
    assert _kinds(llm) == ["month", "faithful", "context", "faithful"]
    assert role.journal_context == CONTEXT_REPLY and role.journal_failed_hash is None


def test_the_description_check_is_more_lenient_than_the_month_check(db_session, llm):
    role = _role(db_session)
    _note(db_session, role, date(2026, 11, 2), "Python work.")
    between = (work_journal.CONTEXT_FAITHFUL_THRESHOLD + work_journal.FAITHFUL_THRESHOLD) / 2
    # The month summary at that score is rejected twice; the description is accepted.
    llm["faithful"] = [between, between]
    work_journal.refresh_journal(db_session, role, llm["service"])
    assert role.journal_months == []

    llm["faithful"] = [0.9, between]
    assert work_journal.refresh_journal(db_session, role, llm["service"]) == []
    assert role.journal_context == CONTEXT_REPLY


def test_a_failing_model_is_a_warning(db_session, llm):
    role = _role(db_session)
    _note(db_session, role, date(2026, 11, 2), "Python work.")
    llm["status"] = 500
    warnings = work_journal.refresh_journal(db_session, role, llm["service"])
    assert len(warnings) == 1 and "November 2026 could not be summarised" in warnings[0]
    assert role.journal_months == []


def test_a_missing_api_key_raises(db_session):
    role = _role(db_session)
    _note(db_session, role, date(2026, 11, 2), "Python work.")
    service = OpenRouterService(db_session, Settings(openrouter_api_key="", cors_origins=[]))
    with pytest.raises(OpenRouterNotConfigured):
        work_journal.refresh_journal(db_session, role, service)


def test_deleting_every_note_of_a_month_drops_its_summary(db_session, llm):
    role = _role(db_session)
    note = _note(db_session, role, date(2026, 11, 2), "Python work.")
    work_journal.refresh_journal(db_session, role, llm["service"])
    db_session.delete(note)
    db_session.commit()
    db_session.refresh(role)
    assert work_journal.is_stale(role)

    llm["calls"].clear()
    work_journal.refresh_journal(db_session, role, llm["service"])
    assert llm["calls"] == []
    assert role.journal_months == []
    assert (role.journal_context, role.journal_tech, role.journal_hash) == (None, None, None)


def test_aggregate_tech_puts_the_most_used_first():
    months = [
        WorkJournalMonth(month=date(2026, 9, 1), tech=["Go", "Docker"], source_hash="a"),
        WorkJournalMonth(month=date(2026, 10, 1), tech=["docker", "Python"], source_hash="b"),
        WorkJournalMonth(month=date(2026, 11, 1), tech=["Rust"], source_hash="c"),
    ]
    assert work_journal.aggregate_tech(months) == ["docker", "Rust", "Python", "Go"]


@pytest.mark.parametrize(
    ("name", "text", "found"),
    [("Go", "Going to the office", False), ("Go", "Wrote it in Go.", True), ("C++", "Some c++ code", True)],
)
def test_mentioned_matches_whole_words(name, text, found):
    assert work_journal.mentioned(name, text) is found


def test_the_users_own_context_and_tech_win(db_session):
    role = _role(db_session, context="My own words.", tech=["Java"], journal_context="Journal words.")
    role.journal_tech = ["Python"]
    assert (role.effective_context, role.effective_tech) == ("My own words.", ["Java"])
    role.context, role.tech = "  ", []
    assert (role.effective_context, role.effective_tech) == ("Journal words.", ["Python"])


def test_cv_and_profile_use_the_effective_values(db_session):
    _role(db_session, context="", journal_context="Journal words.", journal_tech=["Python"])
    _role(db_session, date_start=date(2020, 1, 1), date_end=date(2023, 12, 31), context="Mine.", tech=["Java"])

    roles = load_roles(db_session)
    assert [(r.context, r.tech) for r in roles] == [("Journal words.", ["Python"]), ("Mine.", ["Java"])]
    payload = _work_history_payload(db_session)
    assert [(p["context"], p["tech"]) for p in payload] == [("Journal words.", "Python"), ("Mine.", "Java")]


def test_overdue_current_positions(db_session):
    now = datetime.now(UTC)
    fresh = _role(db_session, created_at=now - timedelta(days=30))
    _note(db_session, fresh, now.date(), "Today.")
    stale = _role(db_session, created_at=now - timedelta(days=30))
    old_note = _note(db_session, stale, now.date() - timedelta(days=8), "Last week.")
    old_note.created_at = now - timedelta(days=8)
    never = _role(db_session, created_at=now - timedelta(days=7, minutes=1))
    _role(db_session, created_at=now - timedelta(days=1))  # just added: not yet
    _role(db_session, created_at=now - timedelta(days=30), date_end=date(2025, 1, 1))  # ended
    _role(db_session, created_at=now - timedelta(days=30), date_start=now.date() + timedelta(days=5))  # pending
    _role(db_session, kind="education", created_at=now - timedelta(days=30))
    db_session.commit()

    assert sorted(work_journal.overdue_role_ids(db_session, now)) == [stale.id, never.id]
