import httpx
import pytest
from sqlalchemy import select

from app.integrations.gmail import AppsScriptError
from app.models import ApplicationEvent, GmailInterviewMail, JobParseResult
from app.services.gmail_monitor import get_monitor_settings
from tests.test_gmail_rejections_task import (  # noqa: F401 - fixture
    FakeClient,
    _application,
    _company,
    _current,
    _message,
    _run,
    openrouter,
)

STEPS = [{"number": 1, "title": "HR call", "duration_minutes": 30}]


class LabelClient(FakeClient):
    def __init__(self, messages, *, fail_label=False):
        super().__init__(messages)
        self.fail_label = fail_label
        self.labelled: list[tuple[str, str]] = []

    def label(self, message_id, label):
        if self.fail_label:
            raise AppsScriptError("unknown action: label")
        self.labelled.append((message_id, label))


@pytest.fixture
def interview(openrouter):  # noqa: F811
    """A mail that is not a rejection but describes the interview process."""
    openrouter["p"] = 0.05
    openrouter["present"] = 0.95
    return openrouter


def _record(db_session, message_id="msg-1"):
    db_session.expire_all()
    return db_session.scalar(select(GmailInterviewMail).where(GmailInterviewMail.message_id == message_id))


def _steps(db_session, application):
    db_session.expire_all()
    return db_session.get(JobParseResult, application.job_parse_result_id).interview_steps


def test_steps_are_stored_and_mail_labelled_but_not_marked_read(db_session, interview):
    application = _application(db_session, _company(db_session, "Acme"), "Backend Developer", i=1)
    client = LabelClient([_message()])

    summary = _run(db_session, client, interview)

    assert _steps(db_session, application) == STEPS
    assert client.labelled == [("msg-1", "interview-steps-registered")]
    assert client.marked == []  # read state untouched
    record = _record(db_session)
    assert record.outcome == "applied" and record.application_id == application.id
    assert _current(db_session, application.id).status.key == "APPLIED"
    assert summary.as_dict()["interview_steps"]["outcomes"] == {"applied": 1}


def test_mail_without_interview_process_is_left_alone(db_session, interview):
    application = _application(db_session, _company(db_session, "Acme"), "Dev", i=1)
    interview["present"] = 0.2
    client = LabelClient([_message()])

    _run(db_session, client, interview)

    assert _record(db_session).outcome == "no_steps"
    assert _steps(db_session, application) is None
    assert client.labelled == []


def test_unfaithful_steps_are_discarded(db_session, interview):
    application = _application(db_session, _company(db_session, "Acme"), "Dev", i=1)
    interview["faithful"] = 0.1
    client = LabelClient([_message()])

    _run(db_session, client, interview)

    assert _record(db_session).outcome == "no_steps"
    assert _steps(db_session, application) is None


def test_existing_steps_are_not_overwritten(db_session, interview):
    application = _application(db_session, _company(db_session, "Acme"), "Dev", i=1)
    existing = [{"number": 1, "title": "Tech interview", "duration_minutes": None}]
    application.job_parse_result.interview_steps = existing
    db_session.commit()
    client = LabelClient([_message()])

    _run(db_session, client, interview)

    assert _record(db_session).outcome == "has_steps"
    assert _steps(db_session, application) == existing
    assert client.labelled == []


def test_application_with_steps_is_not_mistaken_for_another_one(db_session, interview):
    """The mail is about the application that has steps; the other one at the same company
    must not get them."""
    acme = _company(db_session, "Acme")
    backend = _application(db_session, acme, "Backend Developer", i=1)
    backend.job_parse_result.interview_steps = STEPS
    frontend = _application(db_session, acme, "Frontend Engineer", i=2)
    db_session.commit()

    _run(db_session, LabelClient([_message()]), interview)

    assert _record(db_session).outcome == "has_steps"
    assert _steps(db_session, frontend) is None


def test_ambiguous_match_is_left_alone(db_session, interview):
    acme = _company(db_session, "Acme")
    a = _application(db_session, acme, "Python Developer", i=1)
    _application(db_session, acme, "Data Engineer", i=2)
    interview["extract"] = {"company": "Acme", "role": None}

    _run(db_session, LabelClient([_message()]), interview)

    assert _record(db_session).outcome == "ambiguous"
    assert _steps(db_session, a) is None


@pytest.mark.parametrize("status", ["SHORTLISTED", "REJECTED"])
def test_applications_not_open_are_not_touched(db_session, interview, status):
    application = _application(db_session, _company(db_session, "Acme"), "Dev", i=1, status=status)

    _run(db_session, LabelClient([_message()]), interview)

    assert _record(db_session).outcome == "no_match"
    assert _steps(db_session, application) is None


def test_rejection_mails_are_not_checked(db_session, interview):
    _application(db_session, _company(db_session, "Acme"), "Dev", i=1)
    interview["p"] = 0.97

    _run(db_session, LabelClient([_message()]), interview)

    assert _record(db_session) is None


def test_label_failure_keeps_steps_and_is_retried(db_session, interview):
    application = _application(db_session, _company(db_session, "Acme"), "Dev", i=1)
    client = LabelClient([_message()], fail_label=True)

    _run(db_session, client, interview)

    assert _steps(db_session, application) == STEPS
    assert _record(db_session).outcome == "label_failed"

    client.fail_label = False
    calls = len(interview["calls"])
    _run(db_session, client, interview)

    assert _record(db_session).outcome == "applied"
    assert client.labelled == [("msg-1", "interview-steps-registered")]
    assert len(interview["calls"]) == calls  # nothing sent to OpenRouter again
    assert client.marked == []


def test_openrouter_failure_is_retried_next_run(db_session, interview):
    _application(db_session, _company(db_session, "Acme"), "Dev", i=1)
    service = interview["service"]
    real = service._transport

    def flaky(request: httpx.Request) -> httpx.Response:
        if b"describes_interview_process" in request.content:
            return httpx.Response(500, json={})
        return real.handle_request(request)

    service._transport = httpx.MockTransport(flaky)
    summary = _run(db_session, LabelClient([_message()]), interview)

    assert summary.interview.failed == 1
    assert _record(db_session) is None


def _plan(db_session, application):
    db_session.expire_all()
    app = db_session.get(type(application), application.id)
    return [(e.status.key, e.title, e.duration_minutes) for e in app.plan]


def test_steps_are_planned_on_application_without_planned_rounds(db_session, interview):
    application = _application(db_session, _company(db_session, "Acme"), "Dev", i=1)

    _run(db_session, LabelClient([_message()]), interview)

    assert _plan(db_session, application) == [("INTERVIEW", "HR call", 30)]


def test_existing_planned_rounds_are_kept(db_session, interview):
    from app.services.applications import INTERVIEW_STATUS, status_by_key

    application = _application(db_session, _company(db_session, "Acme"), "Dev", i=1)
    application.events.append(
        ApplicationEvent(status=status_by_key(db_session, INTERVIEW_STATUS), planned=True, title="Tech interview")
    )
    db_session.commit()

    _run(db_session, LabelClient([_message()]), interview)

    assert _steps(db_session, application) == STEPS  # the job still gets them
    assert _plan(db_session, application) == [("INTERVIEW", "Tech interview", None)]


def test_configured_interview_label_is_used(db_session, interview):
    _application(db_session, _company(db_session, "Acme"), "Dev", i=1)
    get_monitor_settings(db_session).interview_label = "cv/interviews"
    db_session.commit()
    client = LabelClient([_message()])

    _run(db_session, client, interview)

    assert client.labelled == [("msg-1", "cv/interviews")]
