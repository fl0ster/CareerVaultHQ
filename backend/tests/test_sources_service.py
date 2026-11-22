"""``app.services.sources``: syncing rows with modules, run bookkeeping and relevance."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app import models
from app.services import sources as service
from app.tasks.scrape.sources import SourceInfo
from tests.conftest import ensure_source


@pytest.fixture
def discovered(monkeypatch):
    """Control what ``discover_sources`` reports; a list the test can mutate."""
    infos: list[SourceInfo] = []
    monkeypatch.setattr(service, "discover_sources", lambda: list(infos))
    return infos


# --- sync_sources ------------------------------------------------------------------------


def test_sync_creates_rows_for_discovered_modules(db_session, discovered):
    discovered.append(SourceInfo("alpha", "Alpha", "https://alpha.example"))
    discovered.append(SourceInfo("bad", "bad", None, error="missing NAME"))

    rows = service.sync_sources(db_session)

    assert [(r.key, r.name, r.url, r.module_error, r.enabled) for r in rows] == [
        ("alpha", "Alpha", "https://alpha.example", None, True),
        ("bad", "bad", None, "missing NAME", True),
    ]
    assert rows[0].health == "unknown"
    assert rows[1].health == "broken"


def test_sync_refreshes_metadata_but_keeps_user_settings(db_session, discovered):
    discovered.append(SourceInfo("alpha", "Alpha", "https://alpha.example"))
    row = service.sync_sources(db_session)[0]
    row.enabled = False
    row.scrape_interval_seconds = 7200
    db_session.commit()

    discovered[0] = SourceInfo("alpha", "Alpha v2", "https://alpha.example/v2")
    row = service.sync_sources(db_session)[0]

    assert (row.name, row.url) == ("Alpha v2", "https://alpha.example/v2")
    assert (row.enabled, row.scrape_interval_seconds) == (False, 7200)
    assert db_session.scalars(select(models.ScrapeSource)).all() == [row]  # no duplicate row


def test_sync_marks_missing_modules_and_clears_when_they_return(db_session, discovered):
    discovered.append(SourceInfo("alpha", "Alpha", "https://alpha.example"))
    service.sync_sources(db_session)

    discovered.clear()
    (row,) = service.sync_sources(db_session)
    assert row.module_error == models.ScrapeSource.MODULE_MISSING
    assert row.health == "broken"

    discovered.append(SourceInfo("alpha", "Alpha", "https://alpha.example"))
    (row,) = service.sync_sources(db_session)
    assert row.module_error is None


def test_sync_against_real_modules_includes_skillshot(db_session):
    keys = [r.key for r in service.sync_sources(db_session)]
    assert "skillshot" in keys
    row = service.get_source(db_session, "skillshot")
    assert row.name == "Skillshot"
    assert row.url.startswith("https://www.skillshot.pl")
    assert row.module_error is None


def test_runnable_sources_are_enabled_usable_and_ordered_by_key(db_session):
    ensure_source(db_session, "low")
    ensure_source(db_session, "high")
    ensure_source(db_session, "off", enabled=False)
    ensure_source(db_session, "broken", module_error="missing URL")
    ensure_source(db_session, "also_low")
    db_session.commit()

    assert [r.key for r in service.runnable_sources(db_session)] == ["also_low", "high", "low"]
    assert [r.key for r in service.list_sources(db_session)] == [
        "also_low",
        "broken",
        "high",
        "low",
        "off",
    ]


# --- apply_run_result / health ------------------------------------------------------------


def test_health_follows_run_outcomes():
    row = models.ScrapeSource(key="x", name="X", consecutive_failures=0)
    now = datetime(2026, 11, 16, tzinfo=UTC)
    assert row.health == "unknown"

    service.apply_run_result(row, ok=True, error=None, scraped=10, new=3, now=now)
    assert row.health == "healthy"
    assert (row.last_run_at, row.last_success_at) == (now, now)
    assert (row.last_scraped_count, row.last_new_count, row.last_error) == (10, 3, None)

    service.apply_run_result(row, ok=True, error=None, scraped=0, new=0, now=now)
    assert row.health == "degraded"  # zero listings: markup probably changed

    service.apply_run_result(row, ok=False, error="boom", scraped=0, new=0, now=now)
    assert row.health == "degraded"
    assert (row.consecutive_failures, row.last_error) == (1, "boom")
    assert row.last_success_at == now  # untouched by failures

    service.apply_run_result(row, ok=False, error=None, scraped=0, new=0, now=now)
    service.apply_run_result(row, ok=False, error="boom", scraped=0, new=0, now=now)
    assert row.consecutive_failures == 3
    assert row.health == "failing"

    service.apply_run_result(row, ok=True, error=None, scraped=4, new=0, now=now)
    assert row.consecutive_failures == 0
    assert row.health == "healthy"

    row.module_error = "missing NAME"
    assert row.health == "broken"


# --- source_relevance --------------------------------------------------------------------


def _call() -> models.OpenRouterCall:
    return models.OpenRouterCall(source="t", kind="decision", model="m", input={})


def test_source_relevance_uses_only_the_latest_profile(db_session):
    a = ensure_source(db_session, "a")
    b = ensure_source(db_session, "b")
    c = ensure_source(db_session, "c")  # has jobs but none evaluated
    ensure_source(db_session, "d")  # has no jobs at all
    old = models.CandidateProfile(content="old")
    new = models.CandidateProfile(content="new")
    db_session.add_all([old, new])
    db_session.flush()

    def job(source, i, scores: dict[models.CandidateProfile, float] | None = None):
        j = models.Job(link=f"https://{source.key}.example/{i}", source=source)
        parsed = models.JobParseResult(job=j, title=f"{source.key} {i}")
        db_session.add_all([j, parsed])
        for profile, p in (scores or {}).items():
            db_session.add(
                models.JobEvaluation(
                    job_parse_result=parsed,
                    candidate_profile=profile,
                    match_probability=p,
                    openrouter_call=_call(),
                )
            )

    job(a, 1, {new: 0.9, old: 0.1})
    job(a, 2, {new: 0.3, old: 0.1})
    job(a, 3, {old: 0.1})  # not scored against the new profile
    job(a, 4)  # not even parsed... well, parsed but never evaluated
    job(b, 1, {new: 0.5})
    job(c, 1)
    db_session.commit()

    rel = service.source_relevance(db_session)

    assert rel[a.id] == service.Relevance(job_count=4, evaluated_count=2, avg_match=pytest.approx(0.6), good_match_share=0.5)
    assert rel[b.id] == service.Relevance(job_count=1, evaluated_count=1, avg_match=0.5, good_match_share=1.0)
    assert rel[c.id] == service.Relevance(job_count=1)
    assert set(rel) == {a.id, b.id, c.id}


def test_source_relevance_without_profile_counts_jobs_only(db_session):
    a = ensure_source(db_session, "a")
    db_session.add(models.Job(link="https://a.example/1", source=a))
    db_session.commit()

    assert service.source_relevance(db_session) == {a.id: service.Relevance(job_count=1)}
