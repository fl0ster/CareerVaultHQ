from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fakeredis import FakeStrictRedis
from rq import Queue
from rq.job import Job, JobStatus

from app.config import Settings
from app.db import session_factory
from app.integrations.gmail import AppsScriptClient
from app.scheduler.gmail import GMAIL_JOB_ID, GmailMonitorScheduler
from app.services import gmail_monitor
from app.services.gmail_monitor import get_monitor_settings

BASE = "/api/gmail-monitor"
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _configure(client, **extra):
    body = {
        "email": "me@gmail.com",
        "script_url": "https://script.google.com/macros/s/abc/exec",
        **extra,
    }
    res = client.patch(f"{BASE}/settings", json=body)
    assert res.status_code == 200, res.text
    return res.json()


# --------------------------------------------------------------------------- settings


def test_settings_defaults_and_update(client):
    body = client.get(f"{BASE}/settings").json()
    assert body["enabled"] is False and body["configured"] is False
    assert body["label"] == "rejection-registered"
    assert body["interview_label"] == "interview-steps-registered"
    assert body["threshold"] == 0.9 and body["interval_seconds"] == 1800
    assert body["secret_hint"].startswith("…") and "secret" not in body

    body = _configure(client, label="cv/rejected", interview_label="cv/interviews", threshold=0.95, enabled=True)
    assert body["interview_label"] == "cv/interviews"
    assert body["configured"] is True and body["enabled"] is True
    assert body["label"] == "cv/rejected" and body["threshold"] == 0.95


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-address"},
        {"script_url": "http://insecure.example"},
        {"script_url": "https://evil.example/macros/s/abc/exec"},
        {"script_url": "https://script.google.com.evil.example/macros/s/abc/exec"},
        {"script_url": "https://script.google.com/macros/s/abc/exec?x=https://evil"},
        {"threshold": 0.2},
        {"interval_seconds": 5},
        {"lookback_days": 31},
        {"label": 'x" OR in:anywhere'},
        {"label": ""},
    ],
)
def test_settings_validation(client, payload):
    assert client.patch(f"{BASE}/settings", json=payload).status_code == 422


def test_apps_script_embeds_secret_and_rotation_changes_it(client, db_session):
    first = client.get(f"{BASE}/apps-script").text
    secret = get_monitor_settings(db_session).secret
    assert f"const SECRET = '{secret}';" in first

    hint = client.post(f"{BASE}/settings/rotate-secret").json()["secret_hint"]
    second = client.get(f"{BASE}/apps-script").text
    assert second != first and "__CAREERVAULT_SECRET__" not in second
    assert second.split("const SECRET = '")[1].split("'")[0].endswith(hint.lstrip("…"))


def test_interval_change_resets_schedule(client, db_session):
    row = get_monitor_settings(db_session)
    row.next_run_at = T0
    db_session.commit()

    client.patch(f"{BASE}/settings", json={"interval_seconds": 600})

    db_session.expire_all()
    assert get_monitor_settings(db_session).next_run_at is None


# --------------------------------------------------------------------------- test / run


def _fake_client(email):
    return AppsScriptClient(
        "https://script.google.com/macros/s/abc_DEF-1/exec",
        "s",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"email": email})),
    )


def test_connection_test_reports_account(client, monkeypatch):
    _configure(client)
    monkeypatch.setattr("app.api.routes.gmail_monitor.client_for", lambda row: _fake_client("Me@Gmail.com"))
    assert client.post(f"{BASE}/test").json() == {
        "ok": True,
        "email": "Me@Gmail.com",
        "matches_configured": True,
        "error": None,
    }

    monkeypatch.setattr("app.api.routes.gmail_monitor.client_for", lambda row: _fake_client("other@gmail.com"))
    body = client.post(f"{BASE}/test").json()
    assert body["ok"] is False and "other@gmail.com" in body["error"]


def test_run_requires_configuration(client):
    assert client.post(f"{BASE}/run").status_code == 400


def test_run_enqueues_once(client, fake_queue):
    _configure(client)

    first = client.post(f"{BASE}/run")
    assert first.status_code == 202
    assert first.json()["job_id"] == GMAIL_JOB_ID
    # A second request while the first is still queued returns the same job.
    assert client.post(f"{BASE}/run").json()["job_id"] == GMAIL_JOB_ID
    assert [j.func_name for j in fake_queue.jobs] == ["app.tasks.gmail.rejections.check_rejection_mails"]
    assert client.get(f"{BASE}/jobs/{GMAIL_JOB_ID}").json()["status"] == "queued"
    assert client.get(f"{BASE}/jobs/nope").status_code == 404


def test_mails_listing(client, db_session):
    from app.models import GmailProcessedMail

    db_session.add_all(
        [
            GmailProcessedMail(message_id="a", subject="Hi", outcome="not_rejection"),
            GmailProcessedMail(message_id="b", subject="Sorry", outcome="no_match"),
        ]
    )
    db_session.commit()

    body = client.get(f"{BASE}/mails").json()
    assert [m["message_id"] for m in body] == ["b", "a"]
    assert [m["message_id"] for m in client.get(f"{BASE}/mails?outcome=no_match").json()] == ["b"]


def test_mails_listing_includes_interview_check(client, db_session):
    from app.models import GmailInterviewMail, GmailProcessedMail

    steps = [{"number": 1, "title": "HR call", "duration_minutes": 30}]
    db_session.add_all(
        [
            GmailProcessedMail(message_id="a", subject="Invite", outcome="not_rejection"),
            GmailInterviewMail(message_id="a", outcome="no_match", present_probability=0.99, steps=steps, error="why"),
            GmailProcessedMail(message_id="b", subject="Sorry", outcome="applied"),
        ]
    )
    db_session.commit()

    by_id = {m["message_id"]: m for m in client.get(f"{BASE}/mails").json()}
    interview = by_id["a"]["interview"]
    assert interview["outcome"] == "no_match" and interview["steps"] == steps
    assert interview["present_probability"] == 0.99 and interview["error"] == "why"
    assert by_id["b"]["interview"] is None


# --------------------------------------------------------------------------- scheduler


@pytest.fixture
def scheduler(engine):
    queue = Queue("jobs", connection=FakeStrictRedis())
    sched = GmailMonitorScheduler(queue, Settings(cors_origins=[]), sessions=session_factory(engine))
    return sched, queue


def _set(engine, **fields):
    with session_factory(engine)() as session:
        row = get_monitor_settings(session)
        for name, value in fields.items():
            setattr(row, name, value)
        session.commit()


def test_scheduler_disabled_or_unconfigured(scheduler, engine):
    sched, queue = scheduler
    assert sched.tick(T0) == "disabled"
    _set(engine, enabled=True)
    assert sched.tick(T0) == "disabled"  # no e-mail / URL yet
    assert queue.jobs == []


def test_scheduler_enqueues_when_due_and_plans_next(scheduler, engine):
    sched, queue = scheduler
    _set(
        engine,
        enabled=True,
        email="me@gmail.com",
        script_url="https://script.google.com/macros/s/abc_DEF-1/exec",
        interval_seconds=600,
    )

    assert sched.tick(T0) == "enqueued"
    assert [j.id for j in queue.jobs] == [GMAIL_JOB_ID]
    assert sched.tick(T0 + timedelta(seconds=599)) == "waiting"

    Job.fetch(GMAIL_JOB_ID, connection=queue.connection).set_status(JobStatus.STARTED)
    assert sched.tick(T0 + timedelta(seconds=600)) == "active"

    Job.fetch(GMAIL_JOB_ID, connection=queue.connection).set_status(JobStatus.FINISHED)
    assert sched.tick(T0 + timedelta(seconds=601)) == "enqueued"
    with session_factory(engine)() as session:
        next_at = get_monitor_settings(session).next_run_at.replace(tzinfo=UTC)
    assert next_at == T0 + timedelta(seconds=1201)


def test_new_settings_get_a_secret(db_session):
    row = get_monitor_settings(db_session)
    assert len(row.secret) >= 32
    assert gmail_monitor.get_monitor_settings(db_session).secret == row.secret


def test_workspace_script_url_is_accepted(client):
    url = "https://script.google.com/a/macros/example.com/s/AKfy_cb-1/exec"
    assert client.patch(f"{BASE}/settings", json={"script_url": url}).json()["script_url"] == url
