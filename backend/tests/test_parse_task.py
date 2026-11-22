import importlib

import pytest
from fakeredis import FakeStrictRedis
from rq import Queue
from sqlalchemy import func, select

from app import models
from app.db import init_db, session_factory
from app.services.openrouter import OpenRouterError, OpenRouterNotConfigured
from app.tasks.scrape.sources import skillshot
from tests.conftest import ensure_source

parse_task = importlib.import_module("app.tasks.parse.parse")

HTML = (
    "<html><head><title>Unity Dev dla ACME / Skillshot.pl</title></head>"
    "<body><div id='job_presentation'><h1>Unity Dev </h1>"
    "<p><span>dla</span> <b><a href='/users/7'>ACME</a></b></p>"
    "<p>We need</p><ul><li>Unity</li></ul></div></body></html>"
)


@pytest.fixture
def evaluate_queue(monkeypatch):
    queue = Queue("jobs", connection=FakeStrictRedis())
    monkeypatch.setattr(parse_task, "get_queue", lambda: queue)
    return queue


@pytest.fixture
def extracted_steps(monkeypatch):
    """Replaces the LLM interview-step extraction: set ``state["steps"]`` (a list of
    ``InterviewStep``) or ``state["error"]`` (an exception to raise)."""
    state = {"steps": [], "error": None, "texts": []}

    def fake(service, text):
        state["texts"].append(text)
        if state["error"] is not None:
            raise state["error"]
        return parse_task.InterviewStepsResult(state["steps"], 0.9, 0.9)

    monkeypatch.setattr(parse_task, "extract_interview_steps", fake)
    return state


@pytest.fixture
def extracted_technologies(monkeypatch):
    """Replaces the LLM technology extraction: set ``state["technologies"]`` or
    ``state["error"]``."""
    state = {"technologies": [], "error": None}

    def fake(service, text):
        if state["error"] is not None:
            raise state["error"]
        return state["technologies"]

    monkeypatch.setattr(parse_task, "extract_technologies", fake)
    return state


@pytest.fixture
def task_engine(engine, monkeypatch, evaluate_queue, extracted_steps, extracted_technologies):
    monkeypatch.setattr(parse_task, "init_db", lambda: init_db(engine))
    monkeypatch.setattr(parse_task, "session_factory", lambda: session_factory(engine))
    return engine


def _make_pending(engine, *, source="skillshot", html=HTML, link="https://www.skillshot.pl/jobs/1") -> int:
    with session_factory(engine)() as session:
        job = models.Job(link=link, source=ensure_source(session, source), html=html)
        pending = models.PendingJobParseRun(job=job)
        session.add_all([job, pending])
        session.commit()
        return pending.id


def test_parse_job_dispatches_to_source_and_stores_result(task_engine):
    pending_id = _make_pending(task_engine)

    result = parse_task.parse_job(pending_id)

    assert result["pending_id"] == pending_id
    assert result["source"] == "skillshot"
    assert result["title"] == "Unity Dev"
    assert result["company"] == "ACME"
    assert result["company_match"] == "new"
    assert result["description_chars"] == len("Unity Dev\ndla\nACME\nWe need\nUnity")
    with session_factory(task_engine)() as session:
        pending = session.get(models.PendingJobParseRun, pending_id)
        assert pending.status == "COMPLETED"
        assert pending.parsed_at is not None
        assert pending.error is None

        parsed = session.scalar(select(models.JobParseResult).where(models.JobParseResult.job_id == pending.job_id))
        assert parsed.title == "Unity Dev"
        assert parsed.description == "Unity Dev\ndla\nACME\nWe need\nUnity"
        assert parsed.parsed_at is not None
        assert not hasattr(parsed, "company_name")
        assert parsed.company_id == result["company_id"]
        assert parsed.company.name == "ACME"
        assert parsed.company.normalized_name == "acme"
        assert [a.alias for a in parsed.company.aliases] == ["ACME"]


def test_parse_job_links_typo_to_existing_company(task_engine):
    first = parse_task.parse_job(_make_pending(task_engine))

    with session_factory(task_engine)() as session:
        job = models.Job(
            link="https://www.skillshot.pl/jobs/2",
            source=ensure_source(session),
            html=HTML.replace("ACME", "Techland"),
        )
        pending = models.PendingJobParseRun(job=job)
        session.add_all([job, pending])
        session.commit()
        second_id = pending.id
    second = parse_task.parse_job(second_id)
    assert second["company_match"] == "new"
    assert second["company"] == "Techland"
    assert second["company_id"] != first["company_id"]

    with session_factory(task_engine)() as session:
        job = models.Job(
            link="https://www.skillshot.pl/jobs/3",
            source=ensure_source(session),
            html=HTML.replace("ACME", "Techlnad"),
        )
        pending = models.PendingJobParseRun(job=job)
        session.add_all([job, pending])
        session.commit()
        third_id = pending.id
    third = parse_task.parse_job(third_id)
    assert third["company_match"] == "fuzzy"
    assert third["company_id"] == second["company_id"]

    with session_factory(task_engine)() as session:
        assert session.scalar(select(func.count(models.Company.id))) == 2
        aliases = session.scalars(select(models.CompanyAlias.alias).order_by(models.CompanyAlias.id)).all()
        assert aliases == ["ACME", "Techland", "Techlnad"]
        parse_results = session.scalars(select(models.JobParseResult).order_by(models.JobParseResult.id)).all()
        assert [r.company_id for r in parse_results] == [
            first["company_id"],
            second["company_id"],
            second["company_id"],
        ]


def test_parse_job_without_company_leaves_company_null(task_engine):
    html = "<html><head><title>Unity Dev / Skillshot.pl</title></head><body><p>x</p></body></html>"
    result = parse_task.parse_job(_make_pending(task_engine, html=html))

    assert result["company"] is None
    assert result["company_id"] is None
    assert result["company_match"] is None
    with session_factory(task_engine)() as session:
        assert session.scalar(select(models.JobParseResult)).company_id is None
        assert session.scalar(select(models.Company)) is None


def test_parse_job_enqueues_evaluation_of_the_parsed_job(task_engine, evaluate_queue):
    pending_id = _make_pending(task_engine)

    result = parse_task.parse_job(pending_id)

    queued = evaluate_queue.jobs
    assert len(queued) == 1
    assert queued[0].id == result["evaluate_job"]
    assert queued[0].func_name == "app.tasks.evaluate.evaluate.evaluate_parse_results"
    with session_factory(task_engine)() as session:
        parsed = session.scalar(select(models.JobParseResult))
    assert queued[0].args == ([parsed.id],)
    assert queued[0].meta == {"job_parse_result_id": parsed.id, "job_id": result["job_id"]}


def test_parse_job_survives_queue_outage(task_engine, monkeypatch):
    def boom():
        raise ConnectionError("redis down")

    monkeypatch.setattr(parse_task, "get_queue", boom)
    pending_id = _make_pending(task_engine)

    result = parse_task.parse_job(pending_id)

    assert result["evaluate_job"] is None
    with session_factory(task_engine)() as session:
        assert session.get(models.PendingJobParseRun, pending_id).status == "COMPLETED"


def test_failed_parse_enqueues_nothing(task_engine, evaluate_queue):
    pending_id = _make_pending(task_engine, html=None)

    with pytest.raises(parse_task.JobParseError):
        parse_task.parse_job(pending_id)

    assert evaluate_queue.jobs == []


def test_parse_job_overwrites_previous_result(task_engine):
    pending_id = _make_pending(task_engine)
    parse_task.parse_job(pending_id)

    with session_factory(task_engine)() as session:
        job = session.scalar(select(models.Job))
        job.html = HTML.replace("Unity", "Unreal").replace("Unity Dev", "Unreal Dev")
        again = models.PendingJobParseRun(job_id=job.id)
        session.add(again)
        session.commit()
        again_id = again.id

    parse_task.parse_job(again_id)

    with session_factory(task_engine)() as session:
        results = session.scalars(select(models.JobParseResult)).all()
        assert len(results) == 1
        assert results[0].title == "Unreal Dev"
        assert results[0].description == "Unreal Dev\ndla\nACME\nWe need\nUnreal"


def test_parse_job_marks_failure_when_parser_raises(task_engine, monkeypatch):
    def boom(html):
        raise RuntimeError("bad markup")

    monkeypatch.setattr(skillshot, "parse_description", boom)
    pending_id = _make_pending(task_engine)

    with pytest.raises(RuntimeError, match="bad markup"):
        parse_task.parse_job(pending_id)

    with session_factory(task_engine)() as session:
        pending = session.get(models.PendingJobParseRun, pending_id)
        assert pending.status == "FAILED"
        assert pending.error == "RuntimeError: bad markup"
        assert pending.parsed_at is not None
        assert session.scalar(select(models.JobParseResult)) is None


def test_parse_job_without_html_fails(task_engine):
    pending_id = _make_pending(task_engine, html=None)

    with pytest.raises(parse_task.JobParseError, match="no HTML"):
        parse_task.parse_job(pending_id)

    with session_factory(task_engine)() as session:
        assert session.get(models.PendingJobParseRun, pending_id).status == "FAILED"


def test_parse_job_unknown_source_fails(task_engine):
    pending_id = _make_pending(task_engine, source="nope")

    with pytest.raises(parse_task.JobParseError, match="unknown scrape source"):
        parse_task.parse_job(pending_id)


def test_parse_job_source_without_hook_fails(task_engine, monkeypatch):
    monkeypatch.delattr(skillshot, "parse_title")
    pending_id = _make_pending(task_engine)

    with pytest.raises(parse_task.JobParseError, match="does not define parse_title"):
        parse_task.parse_job(pending_id)

    with session_factory(task_engine)() as session:
        assert session.get(models.PendingJobParseRun, pending_id).status == "FAILED"


def test_skillshot_parse_title_prefers_h1():
    assert skillshot.parse_title(HTML) == "Unity Dev"


def test_skillshot_parse_company_prefers_user_link():
    assert skillshot.parse_company(HTML) == "ACME"


def test_skillshot_parse_company_falls_back_to_title_tag():
    html = "<html><head><title>Unity Dev dla ACME / Skillshot.pl</title></head><body></body></html>"
    assert skillshot.parse_company(html) == "ACME"


def test_skillshot_parse_title_falls_back_to_title_tag():
    html = "<html><head><title>Unity Dev dla ACME / Skillshot.pl</title></head><body></body></html>"
    assert skillshot.parse_title(html) == "Unity Dev"


def test_parse_job_unknown_pending_id(task_engine):
    with pytest.raises(ValueError, match="unknown pending parse run"):
        parse_task.parse_job(999)


def _parsed(engine, pending_id):
    with session_factory(engine)() as session:
        job_id = session.get(models.PendingJobParseRun, pending_id).job_id
        return session.scalar(select(models.JobParseResult).where(models.JobParseResult.job_id == job_id))


def test_parse_job_stores_interview_steps(task_engine, extracted_steps):
    extracted_steps["steps"] = [
        parse_task.InterviewStep(1, "HR call", 30),
        parse_task.InterviewStep(2, "Technical interview"),
    ]
    pending_id = _make_pending(task_engine)

    result = parse_task.parse_job(pending_id)

    assert result["interview_steps"] == 2
    assert extracted_steps["texts"] == ["Unity Dev\ndla\nACME\nWe need\nUnity"]
    assert _parsed(task_engine, pending_id).interview_steps == [
        {"number": 1, "title": "HR call", "duration_minutes": 30},
        {"number": 2, "title": "Technical interview", "duration_minutes": None},
    ]
    assert parse_task.parse_job(pending_id)["interview_steps"] == 2


def test_parse_job_without_interview_steps_stores_empty_list(task_engine):
    pending_id = _make_pending(task_engine)
    assert parse_task.parse_job(pending_id)["interview_steps"] == 0
    assert _parsed(task_engine, pending_id).interview_steps == []


@pytest.mark.parametrize(
    "error",
    [OpenRouterNotConfigured("no key"), OpenRouterError("boom", status_code=500)],
)
def test_interview_step_failure_does_not_fail_the_parse(task_engine, extracted_steps, error):
    extracted_steps["error"] = error
    pending_id = _make_pending(task_engine)

    result = parse_task.parse_job(pending_id)

    assert result["interview_steps"] is None
    assert result["title"] == "Unity Dev"
    assert _parsed(task_engine, pending_id).interview_steps is None
    with session_factory(task_engine)() as session:
        assert session.get(models.PendingJobParseRun, pending_id).status == "COMPLETED"


def test_parse_job_stores_technologies(task_engine, extracted_technologies):
    extracted_technologies["technologies"] = [{"name": "Unity", "key": "unity"}]
    pending_id = _make_pending(task_engine)

    assert parse_task.parse_job(pending_id)["technologies"] == 1
    assert _parsed(task_engine, pending_id).technologies == [{"name": "Unity", "key": "unity"}]
    assert parse_task.parse_job(pending_id)["technologies"] == 1


def test_technology_failure_does_not_fail_the_parse(task_engine, extracted_technologies):
    extracted_technologies["error"] = OpenRouterError("boom", status_code=500)
    pending_id = _make_pending(task_engine)

    result = parse_task.parse_job(pending_id)

    assert result["technologies"] is None
    assert result["title"] == "Unity Dev"
    assert _parsed(task_engine, pending_id).technologies is None
