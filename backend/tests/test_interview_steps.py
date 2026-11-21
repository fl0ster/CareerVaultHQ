"""``extract_interview_steps`` (Jev presence -> chat extraction -> Jev faithfulness)."""

import json

import httpx
import pytest

from app.config import Settings
from app.services.openrouter import OpenRouterService
from app.tasks.parse.parse import (
    FAITHFUL_QUESTION,
    PRESENCE_QUESTION,
    InterviewStep,
    extract_interview_steps,
)

TEXT = "Recruitment process: HR call (30 min), technical interview, meeting with the team."
STEPS = {
    "steps": [
        {"title": "HR call", "duration_minutes": 30},
        {"title": "Technical interview", "duration_minutes": None},
        {"title": "Meeting with the team"},
    ]
}


@pytest.fixture
def openrouter(db_session):
    """OpenRouter mock: ``state["present"]`` / ``state["faithful"]`` are the Jev answers,
    ``state["extract"]`` the chat reply (a dict is sent as JSON)."""
    state = {"present": 0.95, "faithful": 0.9, "extract": STEPS, "calls": []}

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path.endswith("/decisions"):
            (name,) = body["questions"]
            state["calls"].append(name)
            p = state["present"] if name == PRESENCE_QUESTION else state["faithful"]
            return httpx.Response(
                200,
                json={
                    "id": "d",
                    "model": "jev",
                    "answers": {name: {"type": "noul", "noul": p}},
                    "usage": {"cost": 0.001},
                },
            )
        state["calls"].append("chat")
        reply = state["extract"]
        content = reply if isinstance(reply, str) else json.dumps(reply)
        return httpx.Response(
            200,
            json={
                "id": "c",
                "model": "m",
                "choices": [{"message": {"role": "assistant", "content": content}}],
                "usage": {"cost": 0.001},
            },
        )

    settings = Settings(openrouter_api_key="sk-test", cors_origins=[])
    state["service"] = OpenRouterService(
        db_session, settings, transport=httpx.MockTransport(handle)
    )
    return state


def test_steps_are_extracted_and_verified(openrouter):
    result = extract_interview_steps(openrouter["service"], TEXT)
    assert result.steps == [
        InterviewStep(1, "HR call", 30),
        InterviewStep(2, "Technical interview", None),
        InterviewStep(3, "Meeting with the team", None),
    ]
    assert result.present_probability == 0.95
    assert result.faithful_probability == 0.9
    assert openrouter["calls"] == [PRESENCE_QUESTION, "chat", FAITHFUL_QUESTION]


def test_no_process_stops_after_presence_check(openrouter):
    openrouter["present"] = 0.1
    result = extract_interview_steps(openrouter["service"], "We build things. Python, SQL.")
    assert result.steps == []
    assert result.faithful_probability is None
    assert openrouter["calls"] == [PRESENCE_QUESTION]


def test_empty_text_makes_no_calls(openrouter):
    assert extract_interview_steps(openrouter["service"], "  ").steps == []
    assert extract_interview_steps(openrouter["service"], None).steps == []
    assert openrouter["calls"] == []


def test_unfaithful_extraction_is_discarded(openrouter):
    openrouter["faithful"] = 0.2
    result = extract_interview_steps(openrouter["service"], TEXT)
    assert result.steps == []
    assert result.faithful_probability == 0.2


@pytest.mark.parametrize("reply", ["not json", {"steps": "x"}, {"steps": []}])
def test_unusable_extraction_skips_verification(openrouter, reply):
    openrouter["extract"] = reply
    result = extract_interview_steps(openrouter["service"], TEXT)
    assert result.steps == []
    assert openrouter["calls"] == [PRESENCE_QUESTION, "chat"]


def test_fenced_reply_and_bad_items_are_cleaned(openrouter):
    openrouter["extract"] = (
        '```json\n{"steps": [{"title": "  HR   call "}, {"x": 1}, '
        '{"title": "Tech", "duration_minutes": true}, '
        '{"title": "Final", "duration_minutes": 90.0}]}'
        "\n```"
    )
    result = extract_interview_steps(openrouter["service"], TEXT)
    assert result.steps == [
        InterviewStep(1, "HR call"),
        InterviewStep(2, "Tech"),
        InterviewStep(3, "Final", 90),
    ]
