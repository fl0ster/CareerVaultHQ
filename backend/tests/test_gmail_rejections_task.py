import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.config import Settings
from app.integrations.gmail import AppsScriptClient, AppsScriptError, GmailMessage
from app.models import (
    Application,
    ApplicationEvent,
    Company,
    CompanyAlias,
    GmailProcessedMail,
    Job,
    JobParseResult,
)
from app.services.applications import ensure_statuses, record_event
from app.services.gmail_monitor import get_monitor_settings
from app.services.openrouter import OpenRouterService
from app.tasks.gmail import rejections
from tests.conftest import ensure_source

RECEIVED = datetime(2026, 11, 10, 9, 30, tzinfo=UTC)
APPLIED_AT = datetime(2026, 10, 1, tzinfo=UTC)


# --------------------------------------------------------------------------- fakes


class FakeClient:
    def __init__(self, messages, *, fail_mark=False):
        self.messages = messages
        self.fail_mark = fail_mark
        self.marked: list[tuple[str, str]] = []
        self.queries: list[str] = []

    def list_messages(self, lookback_days, label, max_messages=30):
        self.queries.append((lookback_days, label))
        return list(self.messages)

    def mark(self, message_id, label):
        if self.fail_mark:
            raise AppsScriptError("boom")
        self.marked.append((message_id, label))


def _message(i=1, subject="Your application", body="We will not move forward."):
    return GmailMessage(
        id=f"msg-{i}",
        thread_id=f"thr-{i}",
        sender="jobs@acme.example",
        subject=subject,
        received_at=RECEIVED,
        body=body,
    )


@pytest.fixture
def openrouter(db_session):
    """OpenRouter mock: ``state["p"]`` is the rejection probability, ``state["extract"]``
    the chat reply (a dict is sent as JSON)."""
    state = {"p": 0.97, "extract": {"company": "Acme", "role": "Backend Developer"}, "calls": []}

    def handle(request: httpx.Request) -> httpx.Response:
        state["calls"].append(request.url.path)
        if request.url.path.endswith("/decisions"):
            return httpx.Response(
                200,
                json={
                    "id": "d",
                    "model": "jev",
                    "answers": {"is_rejection": {"type": "noul", "noul": state["p"]}},
                    "usage": {"cost": 0.001},
                },
            )
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


def _application(db_session, company, title, *, i, status="APPLIED"):
    ensure_statuses(db_session)
    job = Job(link=f"https://example.com/jobs/{i}", source=ensure_source(db_session))
    parsed = JobParseResult(job=job, title=title, description="d", company=company)
    application = Application(job_parse_result=parsed)
    db_session.add_all([job, parsed, application])
    db_session.flush()
    from app.models import ApplicationStatus

    shortlisted = db_session.scalar(
        select(ApplicationStatus).where(ApplicationStatus.key == "SHORTLISTED")
    )
    application.events.append(
        ApplicationEvent(status=shortlisted, occurred_at=APPLIED_AT - timedelta(days=1))
    )
    db_session.flush()
    if status != "SHORTLISTED":
        record_event(db_session, application, "APPLIED", occurred_at=APPLIED_AT)
    if status in ("INTERVIEW", "REJECTED", "OFFER"):
        db_session.flush()
        db_session.refresh(application)
        record_event(db_session, application, status, occurred_at=APPLIED_AT + timedelta(days=1))
    db_session.commit()
    return application


def _company(db_session, name, *aliases):
    company = Company(name=name, normalized_name=name.lower())
    for alias in aliases:
        company.aliases.append(
            CompanyAlias(alias=alias, normalized_alias=alias.lower(), match_kind="exact")
        )
    db_session.add(company)
    db_session.flush()
    return company


def _run(db_session, client, openrouter):
    settings = get_monitor_settings(db_session)
    return rejections.run_check(db_session, client, openrouter["service"], settings)


def _current(db_session, application_id):
    db_session.expire_all()
    return db_session.get(Application, application_id).current_event


def _record(db_session, message_id="msg-1"):
    return db_session.scalar(
        select(GmailProcessedMail).where(GmailProcessedMail.message_id == message_id)
    )


# --------------------------------------------------------------------------- run_check


def test_high_confidence_rejection_is_registered_and_mail_labelled(db_session, openrouter):
    acme = _company(db_session, "Acme Sp. z o.o.")
    application = _application(db_session, acme, "Backend Developer", i=1)
    client = FakeClient([_message()])

    summary = _run(db_session, client, openrouter)

    event = _current(db_session, application.id)
    assert event.status.key == "REJECTED"
    assert event.source == "gmail" and event.source_ref == "msg-1"
    assert event.occurred_at.replace(tzinfo=UTC) == RECEIVED
    assert client.marked == [("msg-1", "rejection-registered")]
    record = _record(db_session)
    assert record.outcome == "applied" and record.application_id == application.id
    assert record.company == "Acme" and record.probability == pytest.approx(0.97)
    assert summary.outcomes == {"applied": 1}
    assert client.queries == [(7, "rejection-registered")]


def test_low_confidence_mail_is_left_alone(db_session, openrouter):
    application = _application(db_session, _company(db_session, "Acme"), "Dev", i=1)
    openrouter["p"] = 0.6
    client = FakeClient([_message()])

    _run(db_session, client, openrouter)

    assert _current(db_session, application.id).status.key == "APPLIED"
    assert client.marked == []
    assert _record(db_session).outcome == "not_rejection"
    # Only the decision was asked; no extraction call.
    assert [p for p in openrouter["calls"] if p.endswith("/chat/completions")] == []


def test_processed_mail_is_not_sent_to_openrouter_again(db_session, openrouter):
    _application(db_session, _company(db_session, "Acme"), "Dev", i=1)
    openrouter["p"] = 0.1
    client = FakeClient([_message()])
    _run(db_session, client, openrouter)
    calls = len(openrouter["calls"])

    summary = _run(db_session, client, openrouter)

    assert len(openrouter["calls"]) == calls
    assert summary.skipped == 1


def test_role_disambiguates_applications_at_the_same_company(db_session, openrouter):
    acme = _company(db_session, "Acme")
    backend = _application(db_session, acme, "Senior Backend Developer", i=1)
    frontend = _application(db_session, acme, "Frontend Engineer", i=2)
    openrouter["extract"] = {"company": "ACME", "role": "Backend Developer, Senior"}

    _run(db_session, FakeClient([_message()]), openrouter)

    assert _record(db_session).outcome == "applied"
    assert _current(db_session, backend.id).status.key == "REJECTED"
    assert _current(db_session, frontend.id).status.key == "APPLIED"


def test_similar_roles_are_ambiguous(db_session, openrouter):
    acme = _company(db_session, "Acme")
    a = _application(db_session, acme, "Python Developer", i=1)
    b = _application(db_session, acme, "Python Developer II", i=2)
    openrouter["extract"] = {"company": "Acme", "role": "Python Developer"}
    client = FakeClient([_message()])

    _run(db_session, client, openrouter)

    assert _record(db_session).outcome == "ambiguous"
    assert _current(db_session, a.id).status.key == "APPLIED"
    assert _current(db_session, b.id).status.key == "APPLIED"
    assert client.marked == []


def test_several_applications_and_no_role_is_ambiguous(db_session, openrouter):
    acme = _company(db_session, "Acme")
    _application(db_session, acme, "Python Developer", i=1)
    _application(db_session, acme, "Data Engineer", i=2)
    openrouter["extract"] = {"company": "Acme", "role": None}

    _run(db_session, FakeClient([_message()]), openrouter)

    assert _record(db_session).outcome == "ambiguous"


def test_company_alias_and_legal_form_match(db_session, openrouter):
    company = _company(db_session, "Globex Corporation", "globex polska")
    application = _application(db_session, company, "QA", i=1)
    openrouter["extract"] = {"company": "Globex Polska Sp. z o.o.", "role": None}

    _run(db_session, FakeClient([_message()]), openrouter)

    assert _current(db_session, application.id).status.key == "REJECTED"


def test_unknown_company_is_no_match(db_session, openrouter):
    _application(db_session, _company(db_session, "Acme"), "Dev", i=1)
    openrouter["extract"] = {"company": "Initech", "role": "Dev"}
    client = FakeClient([_message()])

    _run(db_session, client, openrouter)

    assert _record(db_session).outcome == "no_match"
    assert client.marked == []


def test_unparseable_extraction(db_session, openrouter):
    _application(db_session, _company(db_session, "Acme"), "Dev", i=1)
    openrouter["extract"] = "I think it's Acme"

    _run(db_session, FakeClient([_message()]), openrouter)

    assert _record(db_session).outcome == "extraction_failed"


@pytest.mark.parametrize("status", ["SHORTLISTED", "REJECTED", "OFFER"])
def test_applications_not_open_are_not_touched(db_session, openrouter, status):
    application = _application(db_session, _company(db_session, "Acme"), "Dev", i=1, status=status)

    _run(db_session, FakeClient([_message()]), openrouter)

    assert _record(db_session).outcome == "no_match"
    events = db_session.get(Application, application.id).history
    assert [e.source for e in events] == ["manual"] * len(events)


def test_interview_stage_application_can_be_rejected(db_session, openrouter):
    application = _application(
        db_session, _company(db_session, "Acme"), "Dev", i=1, status="INTERVIEW"
    )

    _run(db_session, FakeClient([_message()]), openrouter)

    assert _current(db_session, application.id).status.key == "REJECTED"


def test_rejection_is_never_dated_before_the_current_state(db_session, openrouter):
    application = _application(db_session, _company(db_session, "Acme"), "Dev", i=1)
    later = RECEIVED + timedelta(days=2)
    application.current_event.occurred_at = later
    db_session.commit()

    _run(db_session, FakeClient([_message()]), openrouter)

    event = _current(db_session, application.id)
    assert event.status.key == "REJECTED"
    assert event.occurred_at.replace(tzinfo=UTC) == later


def test_mark_failure_keeps_rejection_and_is_retried(db_session, openrouter):
    application = _application(db_session, _company(db_session, "Acme"), "Dev", i=1)
    client = FakeClient([_message()], fail_mark=True)

    _run(db_session, client, openrouter)

    assert _current(db_session, application.id).status.key == "REJECTED"
    assert _record(db_session).outcome == "mark_failed"

    client.fail_mark = False
    _run(db_session, client, openrouter)

    db_session.expire_all()
    assert _record(db_session).outcome == "applied"
    assert client.marked == [("msg-1", "rejection-registered")]


def test_openrouter_failure_is_retried_next_run(db_session, openrouter):
    _application(db_session, _company(db_session, "Acme"), "Dev", i=1)
    service = openrouter["service"]
    service._transport = httpx.MockTransport(lambda req: httpx.Response(500, json={}))

    summary = _run(db_session, FakeClient([_message()]), openrouter)

    assert summary.failed == 1
    assert _record(db_session) is None


@pytest.mark.parametrize(
    ("a", "b", "matches"),
    [
        ("Acme Sp. z o.o.", "ACME", True),
        ("Acme", "Acme Software House", True),
        ("Acme GmbH", "Acme Inc.", True),
        ("Acme", "Acne Studios", False),
        ("IBM", "IBM Polska", False),  # too short for a prefix match
    ],
)
def test_company_similarity(a, b, matches):
    assert (rejections.company_similarity(a, b) >= rejections.COMPANY_THRESHOLD) is matches


# --------------------------------------------------------------------------- entry point


def test_check_rejection_mails_records_failure_when_not_configured(engine, monkeypatch):
    from app.db import session_factory

    monkeypatch.setattr(rejections, "init_db", lambda: None)
    monkeypatch.setattr(rejections, "session_factory", lambda: session_factory(engine))

    with pytest.raises(rejections.NotConfigured):
        rejections.check_rejection_mails()

    with session_factory(engine)() as session:
        settings = get_monitor_settings(session)
        assert settings.last_status == "failed"
        assert "Apps Script" in settings.last_error


# --------------------------------------------------------------------------- client


def test_client_follows_redirect_and_sends_token():
    seen = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url)))
        if request.url.host == "script.google.com":
            assert json.loads(request.content) == {"token": "s3cret", "action": "ping"}
            return httpx.Response(
                302, headers={"Location": "https://script.googleusercontent.com/echo?x=1"}
            )
        return httpx.Response(200, json={"email": "me@gmail.com"})

    client = AppsScriptClient(
        "https://script.google.com/macros/s/abc/exec",
        "s3cret",
        transport=httpx.MockTransport(handle),
    )
    assert client.ping() == "me@gmail.com"
    assert seen[1][0] == "GET"


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(200, json={"error": "unauthorized"}), "secret"),
        (httpx.Response(200, text="<html>Sign in</html>"), "access 'Anyone'"),
        (httpx.Response(500), "HTTP 500"),
    ],
)
def test_client_errors(response, message):
    client = AppsScriptClient(
        "https://script.google.com/macros/s/abc_DEF-1/exec",
        "s",
        transport=httpx.MockTransport(lambda r: response),
    )
    with pytest.raises(AppsScriptError, match=message):
        client.list_messages(7, "l")


def test_client_parses_messages():
    payload = {
        "messages": [
            {
                "id": "m1",
                "thread_id": "t1",
                "from": "HR <hr@acme.example>",
                "subject": "Update",
                "date": "2026-11-10T09:30:00.000Z",
                "body": "Hello",
            }
        ]
    }
    client = AppsScriptClient(
        "https://script.google.com/macros/s/abc_DEF-1/exec",
        "s",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)),
    )
    [message] = client.list_messages(7, "l")
    assert message.sender == "HR <hr@acme.example>"
    assert message.received_at == RECEIVED


def test_client_sends_only_lookback_and_label():
    seen = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"messages": []})

    client = AppsScriptClient(
        "https://script.google.com/macros/s/abc_DEF-1/exec",
        "s",
        transport=httpx.MockTransport(handle),
    )
    client.list_messages(7, "rejection-registered", 30)
    assert seen == [
        {
            "token": "s",
            "action": "list",
            "lookback_days": 7,
            "label": "rejection-registered",
            "max": 30,
        }
    ]


def test_client_refuses_non_google_urls():
    with pytest.raises(AppsScriptError, match="script.google.com"):
        AppsScriptClient("https://evil.example/macros/s/abc/exec", "s")


def test_client_does_not_follow_redirects_off_google():
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "script.google.com":
            return httpx.Response(302, headers={"Location": "https://evil.example/steal"})
        raise AssertionError("must not be called")

    client = AppsScriptClient(
        "https://script.google.com/macros/s/abc/exec", "s", transport=httpx.MockTransport(handle)
    )
    with pytest.raises(AppsScriptError, match="unexpected host"):
        client.ping()


def test_mail_content_is_not_stored(db_session, openrouter):
    from app.models import OpenRouterCall

    _application(db_session, _company(db_session, "Acme"), "Dev", i=1)
    secret_body = "We will not move forward. Reference code XYZ-123."

    _run(db_session, FakeClient([_message(body=secret_body)]), openrouter)

    calls = db_session.scalars(select(OpenRouterCall)).all()
    assert len(calls) == 2
    for call in calls:
        assert call.input["redacted"] is True
        assert "XYZ-123" not in json.dumps(call.input)
        assert "Your application" not in json.dumps(call.input)
