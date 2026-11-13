import json

import httpx
import pytest
from sqlalchemy import select

from app.config import Settings
from app.main import app
from app.models import OpenRouterCall
from app.services.openrouter import (
    OpenRouterError,
    OpenRouterNotConfigured,
    OpenRouterService,
    get_openrouter,
)

BASE = "/api/openrouter"


def _completion(content, *, model="test/model", cost=0.0042, gen_id="gen-1"):
    return {
        "id": gen_id,
        "model": model,
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "cost": cost},
    }


def _decision(answers, *, model="typesafe/jev-1.13-20260917", cost=0.001, gen_id="gen-dec-1"):
    return {
        "id": gen_id,
        "model": model,
        "provider": "TypeSafe",
        "answers": answers,
        "usage": {"input_tokens": 120, "output_tokens": 0, "cost": cost},
    }


NOUL_QUESTIONS = {
    "is_match": {
        "type": "noul",
        "instructions": "Is this job a good match for the candidate?",
        "criteria": {"true": "fits", "false": "does not fit"},
    }
}


@pytest.fixture
def settings():
    return Settings(openrouter_api_key="sk-test", cors_origins=[], openrouter_site_url="http://x")


@pytest.fixture
def requests_seen():
    return []


def _transport(handler, requests_seen):
    def _handle(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request)
        return handler(request)

    return httpx.MockTransport(_handle)


@pytest.fixture
def service_factory(db_session, settings, requests_seen):
    def make(handler):
        return OpenRouterService(db_session, settings, transport=_transport(handler, requests_seen))

    return make


# --- service ---------------------------------------------------------------------------


def test_chat_returns_text_and_records_call(service_factory, db_session, requests_seen):
    service = service_factory(lambda req: httpx.Response(200, json=_completion("hello there")))

    result = service.chat("hi", system="be brief", source="tests.chat", model="foo/bar")

    assert result.text == "hello there"
    assert result.usage.cost == pytest.approx(0.0042)
    req = requests_seen[0]
    assert req.url.path.endswith("/chat/completions")
    assert req.headers["Authorization"] == "Bearer sk-test"
    assert req.headers["HTTP-Referer"] == "http://x"
    body = json.loads(req.content)
    assert body["model"] == "foo/bar"
    assert body["usage"] == {"include": True}
    assert body["messages"] == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "hi"},
    ]

    call = db_session.get(OpenRouterCall, result.call_id)
    assert call.source == "tests.chat"
    assert call.kind == "chat"
    assert call.status == "ok"
    assert call.model == "test/model"  # model as reported by the API
    assert call.cost == pytest.approx(0.0042)
    assert call.prompt_tokens == 10 and call.completion_tokens == 5 and call.total_tokens == 15
    assert call.generation_id == "gen-1"
    assert call.input["messages"][1]["content"] == "hi"
    assert call.output["choices"][0]["message"]["content"] == "hello there"
    assert call.latency_ms is not None


def test_chat_uses_default_model_from_settings(service_factory, requests_seen, settings):
    service = service_factory(lambda req: httpx.Response(200, json=_completion("x")))
    service.chat("hi", source="t")
    assert json.loads(requests_seen[0].content)["model"] == settings.openrouter_chat_model


def test_decide_calls_jev_decisions_api(service_factory, db_session, requests_seen, settings):
    service = service_factory(
        lambda req: httpx.Response(
            200,
            json=_decision(
                {
                    "is_match": {"type": "noul", "noul": 0.82},
                    "team": {
                        "type": "choice",
                        "choice": "backend",
                        "probabilities": {"backend": 0.9, "frontend": 0.1},
                    },
                    "urgency": {"type": "score", "score": 1.4, "probabilities": {}, "legend": {}},
                }
            ),
        )
    )
    state = {"candidate_profile": "python dev", "job_description": "python job"}
    questions = {
        **NOUL_QUESTIONS,
        "team": {"type": "choice", "criteria": {"backend": "b", "frontend": "f"}},
        "urgency": {"type": "score", "criteria": ["low", "high"]},
    }

    result = service.decide(state=state, questions=questions, source="tests.decide")

    assert result.noul("is_match") == pytest.approx(0.82)
    assert result.choice("team") == "backend"
    assert result.score("urgency") == pytest.approx(1.4)
    assert result.answers["is_match"] == {"type": "noul", "noul": 0.82}

    req = requests_seen[0]
    assert str(req.url) == settings.openrouter_decisions_url
    assert req.headers["Authorization"] == "Bearer sk-test"
    body = json.loads(req.content)
    assert body == {
        "model": settings.openrouter_decision_model,
        "state": state,
        "questions": questions,
    }
    assert "messages" not in body and "usage" not in body

    call = db_session.get(OpenRouterCall, result.call_id)
    assert call.kind == "decision"
    assert call.status == "ok"
    assert call.model == "typesafe/jev-1.13-20260917"
    assert call.cost == pytest.approx(0.001)
    assert call.prompt_tokens == 120 and call.completion_tokens == 0 and call.total_tokens == 120
    assert call.generation_id == "gen-dec-1"
    assert call.input["questions"] == questions
    assert call.output["answers"]["is_match"]["noul"] == 0.82


def test_decide_model_override_and_extra(service_factory, requests_seen):
    service = service_factory(
        lambda req: httpx.Response(200, json=_decision({"is_match": {"type": "noul", "noul": 0.1}}))
    )
    service.decide(
        state="text",
        questions=NOUL_QUESTIONS,
        source="t",
        model="typesafe/jev-1.14",
        extra={"session_id": "abc"},
    )
    body = json.loads(requests_seen[0].content)
    assert body["model"] == "typesafe/jev-1.14"
    assert body["session_id"] == "abc"


def test_decide_answer_type_mismatch_and_missing(service_factory):
    service = service_factory(
        lambda req: httpx.Response(200, json=_decision({"is_match": {"type": "refusal"}}))
    )
    result = service.decide(state="x", questions=NOUL_QUESTIONS, source="t")
    with pytest.raises(OpenRouterError, match="expected a 'noul' answer"):
        result.noul("is_match")
    with pytest.raises(OpenRouterError, match="no answer"):
        result.noul("other")


def test_decide_without_answers_marks_call_failed(service_factory, db_session):
    service = service_factory(lambda req: httpx.Response(200, json={"id": "x", "usage": {}}))
    with pytest.raises(OpenRouterError, match="no answers"):
        service.decide(state="x", questions=NOUL_QUESTIONS, source="t")
    call = db_session.scalars(select(OpenRouterCall)).one()
    assert call.status == "failed"


def test_decide_requires_questions(service_factory):
    service = service_factory(lambda req: httpx.Response(200, json={}))
    with pytest.raises(ValueError):
        service.decide(state="x", questions={}, source="t")


def test_http_error_is_recorded(service_factory, db_session):
    service = service_factory(
        lambda req: httpx.Response(402, json={"error": {"message": "Insufficient credits"}})
    )
    with pytest.raises(OpenRouterError, match="402") as exc_info:
        service.chat("hi", source="t")
    assert exc_info.value.status_code == 402
    call = db_session.scalars(select(OpenRouterCall)).one()
    assert call.status == "failed"
    assert "Insufficient credits" in call.error
    assert call.cost is None


def test_transport_error_is_recorded(service_factory, db_session):
    def boom(req):
        raise httpx.ConnectError("no network")

    service = service_factory(boom)
    with pytest.raises(OpenRouterError, match="no network"):
        service.chat("hi", source="t")
    call = db_session.scalars(select(OpenRouterCall)).one()
    assert call.status == "failed"


def test_missing_api_key(db_session):
    service = OpenRouterService(db_session, Settings(openrouter_api_key="", cors_origins=[]))
    with pytest.raises(OpenRouterNotConfigured):
        service.chat("hi", source="t")
    assert db_session.scalars(select(OpenRouterCall)).first() is None


# --- API -------------------------------------------------------------------------------


@pytest.fixture
def api(client, engine, settings, requests_seen):
    """``client`` with the OpenRouter dependency pointed at a mock transport."""
    from app.db import session_factory

    state = {"handler": lambda req: httpx.Response(200, json=_completion("api says hi"))}

    def override():
        with session_factory(engine)() as session:
            yield OpenRouterService(
                session,
                settings,
                transport=_transport(lambda r: state["handler"](r), requests_seen),
            )

    app.dependency_overrides[get_openrouter] = override
    client.state = state
    return client


def test_post_chat(api, requests_seen):
    res = api.post(f"{BASE}/chat", json={"prompt": "hello", "model": "a/b"})
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["text"] == "api says hi"
    assert data["usage"]["cost"] == pytest.approx(0.0042)
    assert json.loads(requests_seen[0].content)["model"] == "a/b"

    detail = api.get(f"{BASE}/calls/{data['call_id']}").json()
    assert detail["source"] == "api.openrouter.chat"
    assert detail["input"]["messages"][0]["content"] == "hello"


def test_post_chat_requires_prompt_or_messages(api):
    assert api.post(f"{BASE}/chat", json={}).status_code == 422


def test_post_chat_with_messages(api, requests_seen):
    res = api.post(
        f"{BASE}/chat",
        json={"messages": [{"role": "user", "content": "x"}], "source": "frontend"},
    )
    assert res.status_code == 200
    assert api.get(f"{BASE}/calls/{res.json()['call_id']}").json()["source"] == "frontend"


def test_post_decide(api, requests_seen):
    api.state["handler"] = lambda req: httpx.Response(
        200, json=_decision({"is_match": {"type": "noul", "noul": 0.7}})
    )
    res = api.post(
        f"{BASE}/decide",
        json={"state": {"job_description": "x"}, "questions": NOUL_QUESTIONS},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["answers"]["is_match"]["noul"] == pytest.approx(0.7)
    assert data["usage"]["cost"] == pytest.approx(0.001)
    assert requests_seen[0].url.path == "/api/alpha/decisions"
    assert api.get(f"{BASE}/calls/{data['call_id']}").json()["source"] == "api.openrouter.decide"


def test_post_decide_requires_questions(api):
    assert api.post(f"{BASE}/decide", json={"state": "x", "questions": {}}).status_code == 422


def test_upstream_error_maps_to_502(api):
    api.state["handler"] = lambda req: httpx.Response(500, text="boom")
    res = api.post(f"{BASE}/chat", json={"prompt": "x"})
    assert res.status_code == 502
    assert "500" in res.json()["detail"]


def test_missing_key_maps_to_503(client, engine):
    from app.db import session_factory

    def override():
        with session_factory(engine)() as session:
            yield OpenRouterService(session, Settings(openrouter_api_key="", cors_origins=[]))

    app.dependency_overrides[get_openrouter] = override
    assert client.post(f"{BASE}/chat", json={"prompt": "x"}).status_code == 503


def test_list_calls_with_filters_and_totals(api):
    api.post(f"{BASE}/chat", json={"prompt": "1"})
    api.post(f"{BASE}/chat", json={"prompt": "2", "source": "other"})
    api.state["handler"] = lambda req: httpx.Response(500, text="boom")
    api.post(f"{BASE}/chat", json={"prompt": "3"})

    page = api.get(f"{BASE}/calls").json()
    assert page["total"] == 3
    assert page["total_cost"] == pytest.approx(0.0084)
    assert [c["status"] for c in page["items"]] == ["failed", "ok", "ok"]

    assert api.get(f"{BASE}/calls", params={"source": "other"}).json()["total"] == 1
    assert api.get(f"{BASE}/calls", params={"status": "failed"}).json()["total"] == 1
    assert api.get(f"{BASE}/calls", params={"kind": "decision"}).json()["total"] == 0
    assert api.get(f"{BASE}/calls/999").status_code == 404
