import importlib

import pytest
from fakeredis import FakeStrictRedis
from rq import Queue
from sqlalchemy import select

from app import models
from app.db import init_db, session_factory
from app.tasks.scrape.sources import skillshot

# ``app.tasks.scrape.scrape`` the attribute is the function; fetch the module explicitly.
scrape_task = importlib.import_module("app.tasks.scrape.scrape")

LISTING = [
    {"link": "https://www.skillshot.pl/jobs/1"},
    {"link": "https://www.skillshot.pl/jobs/2"},
    {"link": "https://www.skillshot.pl/jobs/2"},
]


@pytest.fixture
def task_engine(engine, monkeypatch):
    monkeypatch.setattr(scrape_task, "init_db", lambda: init_db(engine))
    monkeypatch.setattr(scrape_task, "session_factory", lambda: session_factory(engine))
    return engine


@pytest.fixture
def parse_queue(monkeypatch):
    queue = Queue("scrapper", connection=FakeStrictRedis())
    monkeypatch.setattr(scrape_task, "get_scrapper_queue", lambda: queue)
    return queue


@pytest.fixture
def fake_sources(monkeypatch):
    monkeypatch.setattr(scrape_task, "get_available_sources", lambda: ["skillshot"])
    monkeypatch.setattr(skillshot, "fetch_jobs", lambda: list(LISTING))
    fetched: list[str] = []

    def fake_page(url: str) -> str:
        fetched.append(url)
        return f"<html>{url}</html>"

    monkeypatch.setattr(scrape_task, "fetch_page", fake_page)
    return fetched


def test_first_run_inserts_jobs_with_html(task_engine, fake_sources, parse_queue):
    result = scrape_task.scrape("skillshot")

    assert result["count"] == 3
    assert result["new"] == 2
    assert result["duplicates"] == 1  # the same link twice on one listing page
    assert sorted(fake_sources) == [
        "https://www.skillshot.pl/jobs/1",
        "https://www.skillshot.pl/jobs/2",
    ]

    with session_factory(task_engine)() as session:
        run = session.get(models.ScrapeRun, result["scrape_run_id"])
        assert run.status == "finished"
        assert run.source == "skillshot"
        assert (run.scraped_count, run.new_count, run.duplicate_count) == (3, 2, 1)
        assert run.failed_sources is None
        assert run.finished_at is not None

        jobs = session.scalars(select(models.Job).order_by(models.Job.link)).all()
        assert [j.link for j in jobs] == [
            "https://www.skillshot.pl/jobs/1",
            "https://www.skillshot.pl/jobs/2",
        ]
        assert all(j.scrape_run_id == run.id for j in jobs)
        assert all(j.source == "skillshot" for j in jobs)
        assert jobs[0].html == "<html>https://www.skillshot.pl/jobs/1</html>"

        pending = session.scalars(
            select(models.PendingJobParseRun).order_by(models.PendingJobParseRun.job_id)
        ).all()
        assert [p.job_id for p in pending] == [j.id for j in jobs]
        assert all(p.status == "NOT_STARTED" for p in pending)
        assert all(p.parsed_at is None for p in pending)
        assert [p.rq_job_id for p in pending] == result["parse_jobs"]

    # one parse task per inserted job, carrying the pending row id
    queued = parse_queue.jobs
    assert [j.id for j in queued] == result["parse_jobs"]
    assert sorted(j.args[0] for j in queued) == [p.id for p in pending]


def test_second_run_only_counts_duplicates(task_engine, fake_sources, parse_queue):
    first = scrape_task.scrape("skillshot")
    fake_sources.clear()

    second = scrape_task.scrape(None)

    assert second["new"] == 0
    assert second["duplicates"] == 3
    assert second["parse_jobs"] == []
    assert fake_sources == []  # no description fetch for known jobs
    assert len(parse_queue.jobs) == 2  # only the first run enqueued parse tasks
    assert second["scrape_run_id"] != first["scrape_run_id"]

    with session_factory(task_engine)() as session:
        assert (
            session.scalar(
                select(models.Job).where(models.Job.scrape_run_id == second["scrape_run_id"])
            )
            is None
        )
        assert len(session.scalars(select(models.ScrapeRun)).all()) == 2
        run = session.get(models.ScrapeRun, second["scrape_run_id"])
        assert run.source is None


def test_failed_source_is_recorded(task_engine, fake_sources, parse_queue, monkeypatch):
    def boom():
        raise RuntimeError("site down")

    monkeypatch.setattr(skillshot, "fetch_jobs", boom)

    result = scrape_task.scrape("skillshot")

    assert result["failed"] == ["skillshot"]
    assert result["new"] == 0
    with session_factory(task_engine)() as session:
        run = session.get(models.ScrapeRun, result["scrape_run_id"])
        assert run.status == "finished"
        assert run.failed_sources == "skillshot"


def test_unknown_source_raises(task_engine, fake_sources):
    with pytest.raises(ValueError, match="not available"):
        scrape_task.scrape("nope")


def test_skillshot_parse_description():
    html = (
        "<html><body><div id='job_presentation'>"
        "<p>We need</p><ul><li>Unity</li></ul></div></body></html>"
    )
    assert skillshot.parse_description(html) == "We need\nUnity"
