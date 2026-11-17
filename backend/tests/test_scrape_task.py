import importlib
import sys
import types

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
    queue = Queue("jobs", connection=FakeStrictRedis())
    monkeypatch.setattr(scrape_task, "get_queue", lambda: queue)
    return queue


@pytest.fixture
def fake_sources(monkeypatch):
    monkeypatch.setattr("app.tasks.scrape.sources.get_available_sources", lambda: ["skillshot"])
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
        assert run.source.key == "skillshot"
        assert (run.scraped_count, run.new_count, run.duplicate_count) == (3, 2, 1)
        assert run.failed_sources is None
        assert run.finished_at is not None

        jobs = session.scalars(select(models.Job).order_by(models.Job.link)).all()
        assert [j.link for j in jobs] == [
            "https://www.skillshot.pl/jobs/1",
            "https://www.skillshot.pl/jobs/2",
        ]
        assert all(j.scrape_run_id == run.id for j in jobs)
        assert all(j.source.key == "skillshot" for j in jobs)
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


# --- scrape_sources bookkeeping ----------------------------------------------------------


def _source(engine, key="skillshot") -> models.ScrapeSource:
    with session_factory(engine)() as session:
        row = session.scalar(select(models.ScrapeSource).where(models.ScrapeSource.key == key))
        assert row is not None, f"no scrape_sources row for {key}"
        return row


def test_run_updates_source_health(task_engine, fake_sources, parse_queue):
    result = scrape_task.scrape("skillshot")

    row = _source(task_engine)
    assert row.health == "healthy"
    assert row.last_run_at is not None
    assert row.last_success_at == row.last_run_at
    assert (row.last_scraped_count, row.last_new_count) == (3, 2)
    assert row.last_error is None
    assert row.consecutive_failures == 0
    assert result["sources"] == [
        {
            "source": "skillshot",
            "ok": True,
            "error": None,
            "jobs": LISTING,
            "new": 2,
            "duplicates": 1,
        }
    ]


def test_failures_degrade_then_fail_the_source(task_engine, fake_sources, parse_queue, monkeypatch):
    def boom():
        raise RuntimeError("site down")

    monkeypatch.setattr(skillshot, "fetch_jobs", boom)

    scrape_task.scrape("skillshot")
    row = _source(task_engine)
    assert (row.health, row.consecutive_failures) == ("degraded", 1)
    assert row.last_error == "RuntimeError: site down"
    assert row.last_success_at is None

    scrape_task.scrape("skillshot")
    scrape_task.scrape("skillshot")
    row = _source(task_engine)
    assert (row.health, row.consecutive_failures) == ("failing", 3)

    monkeypatch.setattr(skillshot, "fetch_jobs", lambda: list(LISTING))
    scrape_task.scrape("skillshot")
    row = _source(task_engine)
    assert (row.health, row.consecutive_failures) == ("healthy", 0)


def test_disabled_source_is_skipped_by_scrape_all_but_runs_by_name(
    task_engine, fake_sources, parse_queue
):
    scrape_task.scrape(None)  # creates the row
    with session_factory(task_engine)() as session:
        row = session.scalar(select(models.ScrapeSource))
        row.enabled = False
        session.commit()
    fake_sources.clear()

    everything = scrape_task.scrape(None)
    assert everything["sources"] == []
    assert everything["count"] == 0
    assert fake_sources == []

    named = scrape_task.scrape("skillshot")
    assert named["count"] == 3
    assert named["duplicates"] == 3
    assert _source(task_engine).last_run_at is not None


def test_broken_source_cannot_be_run_by_name(task_engine, fake_sources, monkeypatch):
    monkeypatch.setattr(
        "app.tasks.scrape.sources.get_available_sources", lambda: ["skillshot", "junk"]
    )
    monkeypatch.setitem(sys.modules, "app.tasks.scrape.sources.junk", types.ModuleType("junk"))

    with pytest.raises(ValueError, match="not available \\(missing NAME"):
        scrape_task.scrape("junk")

    assert _source(task_engine, "junk").health == "broken"


def test_scrape_all_runs_usable_sources_in_key_order(task_engine, parse_queue, monkeypatch):
    order: list[str] = []

    def stub(key: str) -> types.ModuleType:
        mod = types.ModuleType(f"app.tasks.scrape.sources.{key}")
        mod.NAME, mod.URL = key.title(), f"https://{key}.example"
        mod.fetch_jobs = lambda: order.append(key) or [{"link": f"https://{key}.example/1"}]
        mod.parse_title = mod.parse_company = mod.parse_description = lambda html: ""
        return mod

    monkeypatch.setattr(
        "app.tasks.scrape.sources.get_available_sources", lambda: ["alpha", "beta", "gamma"]
    )
    for key in ("alpha", "beta", "gamma"):
        monkeypatch.setitem(sys.modules, f"app.tasks.scrape.sources.{key}", stub(key))
    monkeypatch.setattr(scrape_task, "fetch_page", lambda url: "<html></html>")

    result = scrape_task.scrape(None)

    assert order == ["alpha", "beta", "gamma"]
    assert [s["source"] for s in result["sources"]] == ["alpha", "beta", "gamma"]
    assert result["new"] == 3
    with session_factory(task_engine)() as session:
        jobs = session.scalars(select(models.Job).order_by(models.Job.id)).all()
        assert [j.source.key for j in jobs] == ["alpha", "beta", "gamma"]
        run = session.scalar(select(models.ScrapeRun))
        assert run.source is None


def test_finished_run_is_recorded_on_the_timeline(task_engine, fake_sources, parse_queue):
    result = scrape_task.scrape("skillshot")

    with session_factory(task_engine)() as session:
        events = session.scalars(select(models.TimelineEvent)).all()
        assert len(events) == 1
        event = events[0]
        assert event.type == "scrape_run"
        assert event.scrape_run_id == result["scrape_run_id"]
        assert event.payload["status"] == "finished"
        assert event.payload["source_key"] == "skillshot"
        assert (event.payload["scraped"], event.payload["new"], event.payload["duplicates"]) == (
            3,
            2,
            1,
        )


def test_crashed_run_is_recorded_on_the_timeline(
    task_engine, fake_sources, parse_queue, monkeypatch
):
    def boom(*_args, **_kwargs):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(scrape_task, "save_jobs", boom)
    with pytest.raises(RuntimeError):
        scrape_task.scrape("skillshot")

    with session_factory(task_engine)() as session:
        (event,) = session.scalars(select(models.TimelineEvent)).all()
        assert event.payload["status"] == "failed"
        assert "db exploded" in event.payload["error"]
