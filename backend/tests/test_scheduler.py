from datetime import UTC, datetime, timedelta

import pytest
from fakeredis import FakeStrictRedis
from rq import Queue
from rq.job import Job, JobStatus

from app.config import Settings
from app.scheduler import scheduler

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
