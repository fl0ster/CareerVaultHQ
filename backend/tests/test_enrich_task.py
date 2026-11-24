"""``app.tasks.parse.enrich``: LLM extractions run for a shortlisted job."""

import importlib

import pytest
from fakeredis import FakeStrictRedis
from rq import Queue
from sqlalchemy import select

from app import models
from app.db import init_db, session_factory
from app.services.applications import INTERVIEW_STATUS, status_by_key
from app.services.openrouter import OpenRouterError, OpenRouterNotConfigured
from tests.conftest import ensure_source

parse_task = importlib.import_module("app.tasks.parse.parse")
enrich_task = importlib.import_module("app.tasks.parse.enrich")

DESCRIPTION = "We need Unity. Process: HR call, then a technical interview."


@pytest.fixture
def llm(monkeypatch):
    """Replaces both LLM extractions: set ``steps`` / ``technologies`` or an ``*_error``."""
    state = {"steps": [], "technologies": [], "steps_error": None, "tech_error": None, "calls": []}

    def fake_steps(service, text):
        state["calls"].append(("steps", text))
        if state["steps_error"] is not None:
            raise state["steps_error"]
        return parse_task.InterviewStepsResult(state["steps"], 0.9, 0.9)

    def fake_technologies(service, text):
        state["calls"].append(("technologies", text))
        if state["tech_error"] is not None:
            raise state["tech_error"]
        return state["technologies"]

    monkeypatch.setattr(parse_task, "extract_interview_steps", fake_steps)
    monkeypatch.setattr(parse_task, "extract_technologies", fake_technologies)
    return state


@pytest.fixture
def task_engine(engine, monkeypatch, llm):
    monkeypatch.setattr(enrich_task, "init_db", lambda: init_db(engine))
    monkeypatch.setattr(enrich_task, "session_factory", lambda: session_factory(engine))
    return engine


def _seed(engine, *, application: bool = True, **fields) -> int:
    with session_factory(engine)() as session:
        job = models.Job(link="https://example.com/jobs/1", source=ensure_source(session))
        parsed = models.JobParseResult(job=job, title="Unity Dev", description=DESCRIPTION, **fields)
        session.add_all([job, parsed])
        if application:
            session.add(models.Application(job_parse_result=parsed))
        session.commit()
        return parsed.id


def _load(engine, parsed_id):
    with session_factory(engine)() as session:
        parsed = session.get(models.JobParseResult, parsed_id)
        app = session.scalar(select(models.Application).where(models.Application.job_parse_result_id == parsed_id))
        plan = [(e.title, e.duration_minutes) for e in app.plan] if app else None
        return parsed.interview_steps, parsed.technologies, plan


def test_enrich_stores_steps_and_technologies_and_plans_rounds(task_engine, llm):
    llm["steps"] = [parse_task.InterviewStep(1, "HR call", 30), parse_task.InterviewStep(2, "Technical interview")]
    llm["technologies"] = [{"name": "Unity", "key": "unity"}]
    parsed_id = _seed(task_engine)

    result = enrich_task.enrich_job(parsed_id)

    assert (result["interview_steps"], result["technologies"], result["planned_rounds"]) == (2, 1, 2)
    assert llm["calls"] == [("steps", DESCRIPTION), ("technologies", DESCRIPTION)]
    steps, technologies, plan = _load(task_engine, parsed_id)
    assert steps == [
        {"number": 1, "title": "HR call", "duration_minutes": 30},
        {"number": 2, "title": "Technical interview", "duration_minutes": None},
    ]
    assert technologies == [{"name": "Unity", "key": "unity"}]
    assert plan == [("HR call", 30), ("Technical interview", None)]


def test_enrich_is_idempotent(task_engine, llm):
    llm["steps"] = [parse_task.InterviewStep(1, "HR call")]
    parsed_id = _seed(task_engine)
    enrich_task.enrich_job(parsed_id)
    llm["calls"].clear()

    result = enrich_task.enrich_job(parsed_id)

    assert llm["calls"] == []  # already-set values are not extracted again
    assert result["planned_rounds"] == 0  # rounds already planned are not added twice
    assert _load(task_engine, parsed_id)[2] == [("HR call", None)]


def test_existing_steps_are_kept(task_engine, llm):
    """Steps already known (e.g. from a recruiter's e-mail) are not overwritten."""
    parsed_id = _seed(task_engine, interview_steps=[{"number": 1, "title": "From mail"}])

    enrich_task.enrich_job(parsed_id)

    assert [c[0] for c in llm["calls"]] == ["technologies"]
    assert _load(task_engine, parsed_id)[0] == [{"number": 1, "title": "From mail"}]


def test_rounds_planned_by_hand_are_left_alone(task_engine, llm):
    llm["steps"] = [parse_task.InterviewStep(1, "HR call")]
    parsed_id = _seed(task_engine)
    with session_factory(task_engine)() as session:
        app = session.scalar(select(models.Application))
        app.events.append(
            models.ApplicationEvent(status=status_by_key(session, INTERVIEW_STATUS), planned=True, title="Mine")
        )
        session.commit()

    assert enrich_task.enrich_job(parsed_id)["planned_rounds"] == 0
    assert _load(task_engine, parsed_id)[2] == [("Mine", None)]


def test_enrich_without_application_only_stores(task_engine, llm):
    llm["steps"] = [parse_task.InterviewStep(1, "HR call")]
    parsed_id = _seed(task_engine, application=False)

    assert enrich_task.enrich_job(parsed_id)["planned_rounds"] == 0
    assert _load(task_engine, parsed_id)[0] == [{"number": 1, "title": "HR call", "duration_minutes": None}]


@pytest.mark.parametrize("error", [OpenRouterNotConfigured("no key"), OpenRouterError("boom", status_code=500)])
def test_llm_failure_leaves_values_unset(task_engine, llm, error):
    llm["steps_error"] = llm["tech_error"] = error
    parsed_id = _seed(task_engine)

    result = enrich_task.enrich_job(parsed_id)

    assert (result["interview_steps"], result["technologies"]) == (None, None)
    assert _load(task_engine, parsed_id) == (None, None, [])


def test_unknown_parse_result(task_engine):
    with pytest.raises(ValueError, match="unknown job parse result"):
        enrich_task.enrich_job(999)


def test_enqueue_enrichment_survives_queue_outage(task_engine):
    class Broken:
        def enqueue(self, *args, **kwargs):
            raise ConnectionError("redis down")

    parsed_id = _seed(task_engine)
    with session_factory(task_engine)() as session:
        parsed = session.get(models.JobParseResult, parsed_id)
        assert enrich_task.enqueue_enrichment(Broken(), None, parsed) is None
        queue = Queue("jobs", connection=FakeStrictRedis())
        rq_id = enrich_task.enqueue_enrichment(queue, None, parsed)
    assert [j.id for j in queue.jobs] == [rq_id]
    assert queue.jobs[0].args == (parsed_id,)
