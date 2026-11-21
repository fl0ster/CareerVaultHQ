import json
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from app.config import Settings
from app.main import app
from app.models import OpenRouterUsage
from app.services.openrouter import (
    OpenRouterError,
    OpenRouterNotConfigured,
    OpenRouterService,
    get_openrouter,
)

BASE = "/api/openrouter"


def _usage(db_session) -> list[OpenRouterUsage]:
    db_session.expire_all()
    return list(db_session.scalars(select(OpenRouterUsage).order_by(OpenRouterUsage.id)))


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


def test_chat_returns_text_and_records_usage(service_factory, db_session, requests_seen):
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

    [row] = _usage(db_session)
    assert row.source == "tests.chat"
    assert row.kind == "chat"
    assert row.status == "ok"
    assert row.model == "test/model"  # model as reported by the API
    assert row.calls == 1
    assert row.cost == pytest.approx(0.0042)
    assert row.prompt_tokens == 10 and row.completion_tokens == 5 and row.total_tokens == 15
    assert row.bucket.minute == 0 and row.bucket.second == 0


def test_calls_with_the_same_key_share_one_hourly_row(service_factory, db_session):
    service = service_factory(lambda req: httpx.Response(200, json=_completion("x")))
    for _ in range(3):
        service.chat("hi", source="tests.chat")
    service.chat("hi", source="tests.other")

    rows = _usage(db_session)
    assert [(r.source, r.calls) for r in rows] == [("tests.chat", 3), ("tests.other", 1)]
    assert rows[0].cost == pytest.approx(3 * 0.0042)
    assert rows[0].total_tokens == 45


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

    [row] = _usage(db_session)
    assert row.kind == "decision"
    assert row.status == "ok"
    assert row.model == "typesafe/jev-1.13-20260917"
    assert row.cost == pytest.approx(0.001)
    assert row.prompt_tokens == 120 and row.completion_tokens == 0 and row.total_tokens == 120


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


def test_decide_without_answers_raises(service_factory):
    service = service_factory(lambda req: httpx.Response(200, json={"id": "x", "usage": {}}))
    with pytest.raises(OpenRouterError, match="no answers"):
        service.decide(state="x", questions=NOUL_QUESTIONS, source="t")


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
    [row] = _usage(db_session)
    assert row.status == "failed"
    assert row.calls == 1
    assert row.cost == 0


def test_transport_error_is_recorded(service_factory, db_session):
    def boom(req):
        raise httpx.ConnectError("no network")

    service = service_factory(boom)
    with pytest.raises(OpenRouterError, match="no network"):
        service.chat("hi", source="t")
    [row] = _usage(db_session)
    assert row.status == "failed"


def test_missing_api_key(db_session):
    service = OpenRouterService(db_session, Settings(openrouter_api_key="", cors_origins=[]))
    with pytest.raises(OpenRouterNotConfigured):
        service.chat("hi", source="t")
    assert _usage(db_session) == []


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
    assert "call_id" not in data
    assert api.get(f"{BASE}/cost").json()["by_source"][0]["key"] == "api.openrouter.chat"


def test_post_chat_requires_prompt_or_messages(api):
    assert api.post(f"{BASE}/chat", json={}).status_code == 422


def test_post_chat_with_messages(api, requests_seen):
    res = api.post(
        f"{BASE}/chat",
        json={"messages": [{"role": "user", "content": "x"}], "source": "frontend"},
    )
    assert res.status_code == 200
    assert api.get(f"{BASE}/cost").json()["facets"]["sources"] == ["frontend"]


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
    sources = api.get(f"{BASE}/cost").json()["facets"]["sources"]
    assert sources == ["api.openrouter.decide"]


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


def test_call_log_endpoints_are_gone(api):
    assert api.get(f"{BASE}/calls").status_code in (404, 405)


def test_cost_report_series_and_breakdowns(api, db_session):
    from datetime import UTC, datetime

    api.post(f"{BASE}/chat", json={"prompt": "1"})
    api.post(f"{BASE}/chat", json={"prompt": "2", "source": "other"})
    api.state["handler"] = lambda req: httpx.Response(500, text="boom")
    api.post(f"{BASE}/chat", json={"prompt": "3"})

    # Move the second call's bucket two days back so the series spans three daily buckets.
    rows = _usage(db_session)
    assert [r.source for r in rows] == ["api.openrouter.chat", "other", "api.openrouter.chat"]
    rows[1].bucket = rows[0].bucket.replace(tzinfo=UTC) - timedelta(days=2)
    db_session.commit()

    report = api.get(f"{BASE}/cost").json()
    assert report["total_calls"] == 3
    assert report["total_cost"] == pytest.approx(0.0084)
    assert report["granularity"] == "day"
    assert [b["calls"] for b in report["series"]] == [1, 0, 2]
    assert [b["cost"] for b in report["series"]] == pytest.approx([0.0042, 0.0, 0.0042])
    assert [b["cumulative_cost"] for b in report["series"]] == pytest.approx(
        [0.0042, 0.0042, 0.0084]
    )
    assert report["by_source"][0] == {
        "key": "api.openrouter.chat",
        "cost": pytest.approx(0.0042),
        "calls": 2,
        "total_tokens": 15,
    }
    assert report["by_model"][0]["key"] == "test/model"  # the failed call logs the default model
    assert report["facets"]["sources"] == ["api.openrouter.chat", "other"]
    assert report["facets"]["statuses"] == ["failed", "ok"]

    filtered = api.get(f"{BASE}/cost", params={"status": "failed"}).json()
    assert filtered["total_calls"] == 1
    assert filtered["total_cost"] == 0
    assert len(filtered["series"]) == 1

    since = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    assert api.get(f"{BASE}/cost", params={"since": since}).json()["total_calls"] == 2
    monthly = api.get(f"{BASE}/cost", params={"granularity": "month"}).json()
    assert len(monthly["series"]) in (1, 2)
    assert monthly["series"][-1]["cumulative_cost"] == pytest.approx(0.0084)

    empty = api.get(f"{BASE}/cost", params={"source": "nope"}).json()
    assert empty["series"] == [] and empty["first_call_at"] is None
    assert api.get(f"{BASE}/cost", params={"granularity": "year"}).status_code == 422
