"""``POST /api/applications/offer-comparison``: LLM hints comparing the open offers, stored
until the offers change."""

import json

import httpx
import pytest
from sqlalchemy import select

from app.config import Settings
from app.db import session_factory
from app.main import app
from app.models import OfferComparison
from app.services.openrouter import OpenRouterService, get_openrouter
from tests.test_applications_api import BASE, seed_cv_inputs, seed_evaluation

URL = f"{BASE}/offer-comparison"


@pytest.fixture
def comparer(client, engine):
    """``client`` with the OpenRouter dependency answering every chat call with
    ``state["reply"]`` (a dict is sent as JSON) or failing with ``state["status"]``,
    recording the prompts."""
    state: dict = {"reply": {}, "status": 200, "prompts": []}

    def handle(request: httpx.Request) -> httpx.Response:
        state["prompts"].append(json.loads(request.content)["messages"][-1]["content"])
        if state["status"] != 200:
            return httpx.Response(state["status"], json={"error": {"message": "boom"}})
        reply = state["reply"]
        content = reply if isinstance(reply, str) else f"```json\n{json.dumps(reply)}\n```"
        return httpx.Response(200, json={"model": "m", "choices": [{"message": {"content": content}}], "usage": {}})

    settings = Settings(openrouter_api_key="test-key", database_url=str(engine.url))

    def override():
        with session_factory(engine)() as session:
            yield OpenRouterService(session, settings, transport=httpx.MockTransport(handle))

    app.dependency_overrides[get_openrouter] = override
    return state


def _application(client, db_session, i, *states, description="Desc", notes=""):
    evaluation = seed_evaluation(db_session, i)
    evaluation.job_parse_result.description = description
    db_session.commit()
    app_id = client.post(BASE, json={"job_evaluation_id": evaluation.id, "notes": notes}).json()["id"]
    for key in states:
        assert client.post(f"{BASE}/{app_id}/events", json={"status": key}).status_code == 201
    return app_id


def _offer(client, db_session, i, **kwargs):
    return _application(client, db_session, i, "APPLIED", "INTERVIEW", "OFFER", **kwargs)


@pytest.fixture
def two_offers(client, db_session):
    seed_cv_inputs(client, db_session)
    first = _offer(client, db_session, 0, description="Salary 30k PLN, fully remote", notes="great team")
    second = _offer(client, db_session, 1, description="Salary 20k PLN, office in Warsaw")
    return first, second


def _reply(first, second):
    return {
        "top_pick": first,
        "top_pick_reason": "Higher pay and fully remote.",
        "offers": [
            {
                "id": first,
                "highlights": [
                    {"kind": "best", "text": "Highest salary: 30k PLN."},
                    {"kind": "unique", "text": "Fully remote"},
                ],
                "watch_out": "Small team",
            },
            {"id": second, "highlights": [{"kind": "unique", "text": "Office in Warsaw"}], "watch_out": None},
        ],
    }


def test_offers_are_compared_once_and_the_comparison_is_stored(client, db_session, comparer, two_offers):
    first, second = two_offers
    _application(client, db_session, 2, "APPLIED")  # not an offer
    comparer["reply"] = _reply(first, second)

    res = client.post(URL)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["top_pick_id"] == first and body["top_pick_reason"] == "Higher pay and fully remote"
    assert [o["application_id"] for o in body["offers"]] == [first, second]
    assert body["offers"][0]["highlights"] == [
        {"kind": "best", "text": "Highest salary: 30k PLN"},
        {"kind": "unique", "text": "Fully remote"},
    ]
    assert body["offers"][0]["watch_out"] == "Small team" and body["offers"][1]["watch_out"] is None
    assert body["generated_at"] is not None

    (prompt,) = comparer["prompts"]
    assert "Salary 30k PLN, fully remote" in prompt and "Salary 20k PLN" in prompt and "great team" in prompt
    assert f"Offer id {first}" in prompt and f"Offer id {second}" in prompt and "Title 2" not in prompt

    # Nothing changed: answered from the stored comparison.
    assert client.post(URL).json() == body
    assert len(comparer["prompts"]) == 1


def test_a_changed_offer_or_refresh_makes_a_new_comparison(client, db_session, comparer, two_offers):
    first, second = two_offers
    comparer["reply"] = _reply(first, second)
    client.post(URL)

    assert client.patch(f"{BASE}/{second}", json={"notes": "they offered equity"}).status_code == 200
    client.post(URL)
    assert len(comparer["prompts"]) == 2 and "they offered equity" in comparer["prompts"][-1]

    client.post(URL, params={"refresh": "true"})
    assert len(comparer["prompts"]) == 3
    # Only the newest comparison is kept.
    assert len(db_session.scalars(select(OfferComparison)).all()) == 1


def test_a_new_offer_is_compared_too(client, db_session, comparer, two_offers):
    first, second = two_offers
    comparer["reply"] = _reply(first, second)
    client.post(URL)
    third = _offer(client, db_session, 3)

    body = client.post(URL).json()
    assert len(comparer["prompts"]) == 2 and f"Offer id {third}" in comparer["prompts"][-1]
    # The model left the new offer out: it gets an empty entry.
    assert body["offers"][-1] == {"application_id": third, "highlights": [], "watch_out": None}


def test_the_answer_is_cleaned_up(client, comparer, two_offers):
    first, second = two_offers
    comparer["reply"] = {
        "top_pick": 999,
        "top_pick_reason": "unknown offer",
        "offers": [
            {"id": 999, "highlights": [{"kind": "best", "text": "ghost"}]},
            {
                "id": str(first),
                "highlights": [
                    {"kind": "best", "text": "a"},
                    {"kind": "amazing", "text": "dropped"},
                    {"kind": "unique", "text": "  b   c  "},
                    {"kind": "strength", "text": ""},
                    {"kind": "strength", "text": "d"},
                    {"kind": "strength", "text": "e"},
                ],
                "watch_out": "null",
            },
        ],
    }
    body = client.post(URL).json()
    assert body["top_pick_id"] is None and body["top_pick_reason"] is None
    assert [o["application_id"] for o in body["offers"]] == [first, second]
    assert [h["text"] for h in body["offers"][0]["highlights"]] == ["a", "b c", "d"]
    assert body["offers"][0]["watch_out"] is None
    assert body["offers"][1]["highlights"] == []


def test_a_single_offer_has_no_top_pick(client, db_session, comparer):
    seed_cv_inputs(client, db_session)
    only = _offer(client, db_session, 0)
    hints = [{"kind": "strength", "text": "Good pay"}]
    comparer["reply"] = {"top_pick": only, "offers": [{"id": only, "highlights": hints}]}

    body = client.post(URL).json()
    assert body["top_pick_id"] is None
    assert body["offers"][0]["highlights"] == [{"kind": "strength", "text": "Good pay"}]


def test_no_offers_means_no_call(client, comparer):
    body = client.post(URL).json()
    assert body == {"top_pick_id": None, "top_pick_reason": None, "offers": [], "generated_at": None}
    assert comparer["prompts"] == []


def test_a_reply_that_is_not_json_is_a_bad_gateway(client, db_session, comparer, two_offers):
    comparer["reply"] = "The first offer is better."
    res = client.post(URL)
    assert res.status_code == 502 and "JSON" in res.json()["detail"]
    assert db_session.scalars(select(OfferComparison)).all() == []


def test_a_failed_call_is_a_bad_gateway(client, comparer, two_offers):
    comparer["status"] = 500
    assert client.post(URL).status_code == 502


def test_without_openrouter_it_is_unavailable(client, db_session, engine):
    seed_cv_inputs(client, db_session)
    _offer(client, db_session, 0)
    settings = Settings(openrouter_api_key="", database_url=str(engine.url))

    def override():
        with session_factory(engine)() as session:
            yield OpenRouterService(session, settings)

    app.dependency_overrides[get_openrouter] = override
    assert client.post(URL).status_code == 503


def test_long_descriptions_keep_their_start_and_end(client, db_session, comparer):
    seed_cv_inputs(client, db_session)
    _offer(client, db_session, 0, description="START " + "x" * 20_000 + " Salary 25k END")
    comparer["reply"] = {"offers": []}
    client.post(URL)
    (prompt,) = comparer["prompts"]
    assert "START" in prompt and "Salary 25k END" in prompt and len(prompt) < 10_000
