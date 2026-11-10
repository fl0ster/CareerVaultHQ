import importlib

import pytest
from sqlalchemy import select

from app import models
from app.db import init_db, make_engine, session_factory
from app.tasks.scrape.description import generic_description
from app.tasks.scrape.sources import skillshot

# ``app.tasks.scrape.scrape`` the attribute is the function; fetch the module explicitly.
scrape_task = importlib.import_module("app.tasks.scrape.scrape")

LISTING = [
    {
        "title": "Unity Developer",
        "link": "https://www.skillshot.pl/jobs/1",
        "date_added": "2026-11-01",
    },
    {
        "title": "C++ Developer",
        "link": "https://www.skillshot.pl/jobs/2",
        "date_added": "2026-11-02",
    },
    {
        "title": "C++ Developer",
        "link": "https://www.skillshot.pl/jobs/2",
        "date_added": "2026-11-02",
    },
]


@pytest.fixture
def engine(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr("app.db.get_engine", lambda: engine)
    monkeypatch.setattr(scrape_task, "init_db", lambda: init_db(engine))
    monkeypatch.setattr(scrape_task, "session_factory", lambda: session_factory(engine))
    return engine


@pytest.fixture
def fake_sources(monkeypatch):
    monkeypatch.setattr(scrape_task, "get_available_sources", lambda: ["skillshot"])
    monkeypatch.setattr(skillshot, "fetch_jobs", lambda: list(LISTING))
    fetched: list[str] = []

    def fake_description(url: str) -> str:
        fetched.append(url)
        return f"description of {url}"

    monkeypatch.setattr(scrape_task, "fetch_description", fake_description)
    return fetched


def test_first_run_inserts_jobs_with_descriptions(engine, fake_sources):
    result = scrape_task.scrape("skillshot")

    assert result["count"] == 3
    assert result["new"] == 2
    assert result["duplicates"] == 1  # the same link twice on one listing page
    assert sorted(fake_sources) == [
        "https://www.skillshot.pl/jobs/1",
        "https://www.skillshot.pl/jobs/2",
    ]

    with session_factory(engine)() as session:
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
        assert jobs[0].description == "description of https://www.skillshot.pl/jobs/1"
        assert jobs[0].date_added == "2026-11-01"


def test_second_run_only_counts_duplicates(engine, fake_sources):
    first = scrape_task.scrape("skillshot")
    fake_sources.clear()

    second = scrape_task.scrape(None)

    assert second["new"] == 0
    assert second["duplicates"] == 3
    assert fake_sources == []  # no description fetch for known jobs
    assert second["scrape_run_id"] != first["scrape_run_id"]

    with session_factory(engine)() as session:
        assert (
            session.scalar(
                select(models.Job).where(models.Job.scrape_run_id == second["scrape_run_id"])
            )
            is None
        )
        assert len(session.scalars(select(models.ScrapeRun)).all()) == 2
        run = session.get(models.ScrapeRun, second["scrape_run_id"])
        assert run.source is None


def test_failed_source_is_recorded(engine, fake_sources, monkeypatch):
    def boom():
        raise RuntimeError("site down")

    monkeypatch.setattr(skillshot, "fetch_jobs", boom)

    result = scrape_task.scrape("skillshot")

    assert result["failed"] == ["skillshot"]
    assert result["new"] == 0
    with session_factory(engine)() as session:
        run = session.get(models.ScrapeRun, result["scrape_run_id"])
        assert run.status == "finished"
        assert run.failed_sources == "skillshot"


def test_unknown_source_raises(engine, fake_sources):
    with pytest.raises(ValueError, match="not available"):
        scrape_task.scrape("nope")


def test_skillshot_parse_description():
    html = (
        "<html><body><div id='job_presentation'>"
        "<p>We need</p><ul><li>Unity</li></ul></div></body></html>"
    )
    assert skillshot.parse_description(html, "https://www.skillshot.pl/jobs/1") == "We need\nUnity"


def test_generic_description_prefers_jsonld():
    html = """<html><head><script type="application/ld+json">
    {"@type": "JobPosting", "title": "Dev", "hiringOrganization": {"name": "ACME"},
     "description": "<p>%s</p>"}
    </script></head><body><main>short</main></body></html>""" % ("x" * 120)
    text = generic_description(html)
    assert text.startswith("Title: Dev\nCompany: ACME")
    assert "x" * 120 in text
