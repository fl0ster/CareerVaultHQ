import random
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest
from fakeredis import FakeStrictRedis
from rq import Queue
from rq.job import Job, JobStatus

from app.config import Settings
from app.db import session_factory
from app.scheduler import scheduler
from app.services import sources as sources_service
from app.tasks.scrape.sources import SourceInfo
from tests.conftest import ensure_source

T0 = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def queue():
    return Queue("jobs", connection=FakeStrictRedis())


@pytest.fixture
def sched(queue):
    settings = Settings(
        cors_origins=[],
        evaluate_interval_seconds=600,
        evaluate_max_backoff_seconds=3000,
        evaluate_batch_size=7,
    )
    return scheduler.EvaluationScheduler(queue, settings)


def _set_status(queue, status):
    job = Job.fetch(scheduler.EVALUATE_JOB_ID, connection=queue.connection)
    job.set_status(status)


def test_first_tick_enqueues_catch_up_with_batch_size(sched, queue):
    assert sched.tick(T0) == "enqueued"

    jobs = queue.jobs
    assert [j.id for j in jobs] == [scheduler.EVALUATE_JOB_ID]
    assert jobs[0].func_name == "app.tasks.evaluate.evaluate.evaluate_pending_jobs"
    assert jobs[0].args == (7,)


def test_tick_waits_for_the_interval(sched, queue):
    sched.tick(T0)
    assert sched.tick(T0 + timedelta(minutes=9)) == "waiting"
    assert len(queue.jobs) == 1


def test_tick_does_not_enqueue_while_previous_is_active(sched, queue):
    sched.tick(T0)
    for status in (JobStatus.QUEUED, JobStatus.STARTED):
        _set_status(queue, status)
        assert sched.tick(T0 + timedelta(minutes=11)) == "active"


def test_tick_replaces_finished_run_after_interval(sched, queue):
    sched.tick(T0)
    _set_status(queue, JobStatus.FINISHED)

    assert sched.tick(T0 + timedelta(minutes=10)) == "enqueued"
    assert len(queue.jobs) == 1
    assert sched.consecutive_failures == 0


def test_failed_runs_back_off_exponentially_up_to_the_cap(sched, queue):
    now = T0
    sched.tick(now)
    # interval is 10 min, cap 50 min: 20, 40, then 50, 50
    for failures, minutes in enumerate([20, 40, 50, 50], start=1):
        _set_status(queue, JobStatus.FAILED)
        now = sched.next_run_at
        assert sched.tick(now - timedelta(seconds=1)) == "waiting"
        assert sched.tick(now) == "enqueued"
        assert sched.consecutive_failures == failures
        assert sched.next_run_at == now + timedelta(minutes=minutes)


def test_success_after_failures_resets_backoff(sched, queue):
    sched.tick(T0)
    _set_status(queue, JobStatus.FAILED)
    sched.tick(T0 + timedelta(minutes=10))
    assert sched.consecutive_failures == 1
    assert sched.next_run_at == T0 + timedelta(minutes=30)

    _set_status(queue, JobStatus.FINISHED)
    assert sched.tick(T0 + timedelta(minutes=30)) == "enqueued"
    assert sched.consecutive_failures == 0
    assert sched.next_run_at == T0 + timedelta(minutes=40)


@pytest.fixture
def cleanup_sched(queue):
    settings = Settings(cors_origins=[], cleanup_interval_seconds=86400, cleanup_max_age_days=45)
    return scheduler.CleanupScheduler(queue, settings)


def test_cleanup_enqueued_daily_with_max_age(cleanup_sched, queue):
    assert cleanup_sched.tick(T0) == "enqueued"
    job = Job.fetch(scheduler.CLEANUP_JOB_ID, connection=queue.connection)
    assert job.func_name == "app.tasks.cleanup.cleanup_old_jobs"
    assert job.args == (45,)

    assert cleanup_sched.tick(T0 + timedelta(hours=23)) == "waiting"
    assert cleanup_sched.tick(T0 + timedelta(days=1)) == "active"  # still queued

    job.set_status(JobStatus.FINISHED)
    assert cleanup_sched.tick(T0 + timedelta(days=1)) == "enqueued"


# --- ScrapeScheduler ---

HOUR = timedelta(hours=1)


@pytest.fixture
def scrape_sched(queue, engine, monkeypatch):
    monkeypatch.setattr(
        sources_service,
        "discover_sources",
        lambda: [
            SourceInfo("alpha", "Alpha", "https://alpha.example"),
            SourceInfo("beta", "Beta", "https://beta.example"),
            SourceInfo("off", "Off", "https://off.example"),
            SourceInfo("bad", "bad", None, error="missing NAME"),
        ],
    )
    with session_factory(engine)() as session:
        for key in ("alpha", "beta", "off"):
            ensure_source(session, key)
        sources_service.get_source(session, "off").enabled = False
        session.commit()
    settings = Settings(cors_origins=[], scrape_interval_seconds=3600, scrape_jitter_ratio=0.5)
    return scheduler.ScrapeScheduler(
        queue, settings, sessions=session_factory(engine), rng=random.Random(1)
    )


def _row(engine, key):
    with session_factory(engine)() as session:
        return sources_service.get_source(session, key)


def _next(engine, key):
    return scheduler._aware(_row(engine, key).next_scrape_at)


def test_scrape_plans_only_enabled_usable_sources_with_jitter(scrape_sched, engine, queue):
    assert scrape_sched.tick(T0) == {"alpha": "planned", "beta": "planned"}
    assert queue.jobs == []

    alpha, beta = _next(engine, "alpha"), _next(engine, "beta")
    for planned in (alpha, beta):
        assert T0 <= planned <= T0 + HOUR / 2  # never ran: now + up to 50% of the interval
    assert alpha != beta  # spread out, not at the same moment
    assert _row(engine, "off").next_scrape_at is None


def test_scrape_enqueues_due_source_and_replans(scrape_sched, engine, queue):
    scrape_sched.tick(T0)
    alpha = _next(engine, "alpha")
    beta = _next(engine, "beta")
    first, second = sorted([("alpha", alpha), ("beta", beta)], key=lambda kv: kv[1])

    actions = scrape_sched.tick(first[1])
    assert actions[first[0]] == "enqueued"
    assert actions[second[0]] == "waiting"

    (job,) = queue.jobs
    assert job.id == scheduler.SCRAPE_JOB_ID_PREFIX + first[0]
    assert job.func_name == "app.tasks.scrape.scrape.scrape"
    assert job.args == (first[0],)
    assert job.meta["source"] == first[0]

    replanned = _next(engine, first[0])
    assert first[1] + HOUR <= replanned <= first[1] + HOUR * 1.5


def test_scrape_does_not_enqueue_while_previous_run_is_active(scrape_sched, engine, queue):
    scrape_sched.tick(T0)
    due = _next(engine, "alpha")
    scrape_sched.tick(due)
    later = _next(engine, "alpha")

    assert scrape_sched.tick(later)["alpha"] == "active"  # still queued
    assert len([j for j in queue.jobs if j.args == ("alpha",)]) == 1

    Job.fetch(scheduler.SCRAPE_JOB_ID_PREFIX + "alpha", connection=queue.connection).set_status(
        JobStatus.FINISHED
    )
    assert scrape_sched.tick(later)["alpha"] == "enqueued"


def test_scrape_uses_per_source_interval_and_last_run(scrape_sched, engine):
    with session_factory(engine)() as session:
        row = sources_service.get_source(session, "alpha")
        row.scrape_interval_seconds = 4 * 3600
        row.last_run_at = T0 - HOUR
        session.commit()

    scrape_sched.tick(T0)

    # last run + 4h = T0 + 3h, plus up to 50% of 4h of jitter
    assert T0 + 3 * HOUR <= _next(engine, "alpha") <= T0 + 5 * HOUR


def test_scheduler_module_imports_on_its_own():
    """``python -m app.scheduler.scheduler`` loads it first, before anything else."""
    subprocess.run([sys.executable, "-c", "import app.scheduler.scheduler"], check=True)
