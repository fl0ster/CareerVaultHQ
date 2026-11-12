import importlib

import pytest
from sqlalchemy import select

from app import models
from app.db import init_db, session_factory
from app.tasks.scrape.sources import skillshot

parse_task = importlib.import_module("app.tasks.parse.parse")

HTML = (
    "<html><head><title>Unity Dev dla ACME / Skillshot.pl</title></head>"
    "<body><div id='job_presentation'><h1>Unity Dev </h1>"
    "<p><span>dla</span> <b><a href='/users/7'>ACME</a></b></p>"
    "<p>We need</p><ul><li>Unity</li></ul></div></body></html>"
)


@pytest.fixture
def task_engine(engine, monkeypatch):
    monkeypatch.setattr(parse_task, "init_db", lambda: init_db(engine))
    monkeypatch.setattr(parse_task, "session_factory", lambda: session_factory(engine))
    return engine


def _make_pending(engine, *, source="skillshot", html=HTML) -> int:
    with session_factory(engine)() as session:
        job = models.Job(link="https://www.skillshot.pl/jobs/1", source=source, html=html)
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
    assert result["description_chars"] == len("Unity Dev\ndla\nACME\nWe need\nUnity")
    with session_factory(task_engine)() as session:
        pending = session.get(models.PendingJobParseRun, pending_id)
        assert pending.status == "COMPLETED"
        assert pending.parsed_at is not None
        assert pending.error is None

        parsed = session.scalar(
            select(models.JobParseResult).where(models.JobParseResult.job_id == pending.job_id)
        )
        assert parsed.title == "Unity Dev"
        assert parsed.company == "ACME"
        assert parsed.description == "Unity Dev\ndla\nACME\nWe need\nUnity"
        assert parsed.parsed_at is not None


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
