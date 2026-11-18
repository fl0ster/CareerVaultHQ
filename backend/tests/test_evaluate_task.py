import importlib
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app import models
from app.config import Settings
from app.db import init_db, session_factory
from app.services.openrouter import OpenRouterService
from tests.conftest import ensure_source

evaluate_task = importlib.import_module("app.tasks.evaluate.evaluate")


def _decision(probability, *, model="typesafe/jev-1.14", gen_id="gen-dec-1"):
    return {
        "id": gen_id,
        "model": model,
        "answers": {"is_match": {"type": "noul", "noul": probability}},
        "usage": {"input_tokens": 100, "output_tokens": 0, "cost": 0.001},
    }


@pytest.fixture
def requests_seen():
    return []


@pytest.fixture
def task_engine(engine, monkeypatch, requests_seen):
    """Redirect the task to the temporary database and a mocked OpenRouter."""
    monkeypatch.setattr(evaluate_task, "init_db", lambda: init_db(engine))
    monkeypatch.setattr(evaluate_task, "session_factory", lambda: session_factory(engine))
    settings = Settings(openrouter_api_key="sk-test", cors_origins=[])
    state = {"handler": lambda req: httpx.Response(200, json=_decision(0.5))}

    def _handle(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request)
        return state["handler"](request)

    def make_service(session, _settings=None, **_kwargs):
        return OpenRouterService(session, settings, transport=httpx.MockTransport(_handle))

    monkeypatch.setattr(evaluate_task, "OpenRouterService", make_service)
    engine.set_handler = lambda handler: state.__setitem__("handler", handler)
    return engine


def _seed(engine, *, profiles=("Senior Unity developer",), jobs=2) -> dict:
    with session_factory(engine)() as session:
        profile_ids = []
        for content in profiles:
            profile = models.CandidateProfile(content=content)
            session.add(profile)
            session.flush()
            profile_ids.append(profile.id)
        parsed_ids = []
        acme = models.Company(name="ACME", normalized_name="acme")
        session.add(acme)
        for i in range(jobs):
            job = models.Job(link=f"https://example.com/jobs/{i}", source=ensure_source(session))
            parsed = models.JobParseResult(
                job=job, title=f"Job {i}", company=acme, description=f"Needs Unity {i}"
            )
            session.add_all([job, parsed])
            session.flush()
            parsed_ids.append(parsed.id)
        session.commit()
        return {"profile_ids": profile_ids, "parsed_ids": parsed_ids}


def test_evaluate_pending_jobs_scores_every_unevaluated_job(task_engine, requests_seen):
    seeded = _seed(task_engine)
    scores = iter([0.91, 0.12])
    task_engine.set_handler(lambda req: httpx.Response(200, json=_decision(next(scores))))

    result = evaluate_task.evaluate_pending_jobs()

    assert result["candidate_profile_id"] == seeded["profile_ids"][0]
    assert result["pending"] == 2
    assert result["evaluated"] == 2
    assert result["failed"] == 0
    assert [e["match_probability"] for e in result["evaluations"]] == [0.91, 0.12]
    assert len(requests_seen) == 2
    body = requests_seen[0].read()
    assert b"Senior Unity developer" in body and b"Needs Unity 0" in body

    with session_factory(task_engine)() as session:
        rows = session.scalars(select(models.JobEvaluation).order_by(models.JobEvaluation.id)).all()
        pairs = [(r.job_parse_result_id, r.candidate_profile_id, r.match_probability) for r in rows]
        assert pairs == [
            (seeded["parsed_ids"][0], seeded["profile_ids"][0], 0.91),
            (seeded["parsed_ids"][1], seeded["profile_ids"][0], 0.12),
        ]
        assert all(r.openrouter_call_id is not None for r in rows)
        calls = session.scalars(select(models.OpenRouterCall)).all()
        assert all(c.model == "typesafe/jev-1.14" for c in calls)
        assert {c.source for c in calls} == {"tasks.evaluate"}
        assert {c.kind for c in calls} == {"decision"}


def test_evaluate_pending_jobs_skips_evaluated_and_uses_latest_profile(task_engine, requests_seen):
    seeded = _seed(task_engine, profiles=("old profile", "new profile"), jobs=2)
    old_id, new_id = seeded["profile_ids"]
    with session_factory(task_engine)() as session:
        # Evaluated against the old profile only -> still pending for the new one.
        session.add(
            models.JobEvaluation(
                job_parse_result_id=seeded["parsed_ids"][0],
                candidate_profile_id=old_id,
                match_probability=0.3,
            )
        )
        # Already evaluated against the new profile -> skipped.
        session.add(
            models.JobEvaluation(
                job_parse_result_id=seeded["parsed_ids"][1],
                candidate_profile_id=new_id,
                match_probability=0.7,
            )
        )
        session.commit()

    result = evaluate_task.evaluate_pending_jobs()

    assert result["candidate_profile_id"] == new_id
    assert result["pending"] == 1
    assert result["evaluated"] == 1
    assert result["evaluations"][0]["job_parse_result_id"] == seeded["parsed_ids"][0]
    assert len(requests_seen) == 1
    assert b"new profile" in requests_seen[0].read()

    # Nothing left to do on the next run.
    assert evaluate_task.evaluate_pending_jobs()["pending"] == 0
    assert len(requests_seen) == 1


def test_evaluate_pending_jobs_continues_after_a_failed_call(task_engine, requests_seen):
    seeded = _seed(task_engine, jobs=3)
    responses = iter(
        [
            httpx.Response(200, json=_decision(0.8)),
            httpx.Response(502, json={"error": {"message": "provider down"}}),
            httpx.Response(200, json=_decision(0.2)),
        ]
    )
    task_engine.set_handler(lambda req: next(responses))

    result = evaluate_task.evaluate_pending_jobs()

    assert result["pending"] == 3
    assert result["evaluated"] == 2
    assert result["failed"] == 1
    assert [e["job_parse_result_id"] for e in result["evaluations"]] == [
        seeded["parsed_ids"][0],
        seeded["parsed_ids"][2],
    ]
    with session_factory(task_engine)() as session:
        assert (
            session.scalar(
                select(models.JobEvaluation).where(
                    models.JobEvaluation.job_parse_result_id == seeded["parsed_ids"][1]
                )
            )
            is None
        )
        failed_calls = session.scalars(
            select(models.OpenRouterCall).where(models.OpenRouterCall.status == "failed")
        ).all()
        assert len(failed_calls) == 1


def test_evaluate_pending_jobs_is_idempotent_for_a_pair(task_engine, requests_seen):
    seeded = _seed(task_engine, jobs=1)

    first = evaluate_task.evaluate_pending_jobs()
    second = evaluate_task.evaluate_pending_jobs()

    assert first["evaluated"] == 1
    assert second == {
        "candidate_profile_id": seeded["profile_ids"][0],
        "pending": 0,
        "evaluated": 0,
        "failed": 0,
        "skipped": 0,
        "evaluations": [],
    }
    assert len(requests_seen) == 1
    with session_factory(task_engine)() as session:
        assert len(session.scalars(select(models.JobEvaluation)).all()) == 1


def test_evaluate_pending_jobs_discards_duplicate_from_concurrent_run(task_engine, requests_seen):
    """A row inserted by another run between selection and commit is kept, ours dropped."""
    seeded = _seed(task_engine, jobs=1)
    parsed_id, profile_id = seeded["parsed_ids"][0], seeded["profile_ids"][0]

    def race(request):
        with session_factory(task_engine)() as other:
            other.add(
                models.JobEvaluation(
                    job_parse_result_id=parsed_id,
                    candidate_profile_id=profile_id,
                    match_probability=0.42,
                )
            )
            other.commit()
        return httpx.Response(200, json=_decision(0.99))

    task_engine.set_handler(race)

    result = evaluate_task.evaluate_pending_jobs()

    assert result["pending"] == 1
    assert result["evaluated"] == 0
    assert result["skipped"] == 1
    assert result["evaluations"] == []
    with session_factory(task_engine)() as session:
        rows = session.scalars(select(models.JobEvaluation)).all()
        assert [(r.job_parse_result_id, r.match_probability) for r in rows] == [(parsed_id, 0.42)]
        # The OpenRouter call itself is still logged.
        assert session.scalar(select(models.OpenRouterCall)).status == "ok"


def test_evaluate_parse_results_scores_only_given_ids(task_engine, requests_seen):
    seeded = _seed(task_engine, jobs=3)
    wanted = seeded["parsed_ids"][1]

    result = evaluate_task.evaluate_parse_results([wanted])

    assert result["pending"] == 1
    assert [e["job_parse_result_id"] for e in result["evaluations"]] == [wanted]
    assert len(requests_seen) == 1
    # Calling again for the same job is a no-op; the other two are still pending.
    assert evaluate_task.evaluate_parse_results([wanted])["pending"] == 0
    assert evaluate_task.evaluate_parse_results([])["pending"] == 0
    assert evaluate_task.evaluate_pending_jobs()["pending"] == 2


def test_jobs_parsed_over_a_week_ago_are_not_evaluated(task_engine, requests_seen):
    seeded = _seed(task_engine, jobs=3)
    stale, fresh, borderline = seeded["parsed_ids"]
    now = datetime.now(UTC)
    with session_factory(task_engine)() as session:
        session.get(models.JobParseResult, stale).parsed_at = now - timedelta(days=8)
        session.get(models.JobParseResult, fresh).parsed_at = now - timedelta(days=1)
        session.get(models.JobParseResult, borderline).parsed_at = now - timedelta(days=6, hours=23)
        session.commit()

    result = evaluate_task.evaluate_pending_jobs()

    assert [e["job_parse_result_id"] for e in result["evaluations"]] == [fresh, borderline]
    assert len(requests_seen) == 2
    # Asking for the stale one explicitly does not evaluate it either.
    assert evaluate_task.evaluate_parse_results([stale])["pending"] == 0
    assert len(requests_seen) == 2


def test_failed_call_is_recorded_and_retried_only_after_backoff(task_engine, requests_seen):
    seeded = _seed(task_engine, jobs=1)
    parsed_id, profile_id = seeded["parsed_ids"][0], seeded["profile_ids"][0]
    task_engine.set_handler(
        lambda req: httpx.Response(502, json={"error": {"message": "provider down"}})
    )

    assert evaluate_task.evaluate_pending_jobs()["failed"] == 1
    with session_factory(task_engine)() as session:
        failure = session.scalar(select(models.JobEvaluationFailure))
        assert (failure.job_parse_result_id, failure.candidate_profile_id) == (
            parsed_id,
            profile_id,
        )
        assert failure.attempts == 1
        assert "provider down" in failure.last_error
        first_backoff = failure.next_attempt_at - failure.last_attempt_at
        assert first_backoff == timedelta(seconds=Settings().evaluate_retry_backoff_seconds)

    # Still inside the backoff window: nothing is retried, by either entry point.
    assert evaluate_task.evaluate_pending_jobs()["pending"] == 0
    assert evaluate_task.evaluate_parse_results([parsed_id])["pending"] == 0
    assert len(requests_seen) == 1

    # Once the window has passed the job is retried and the backoff doubles.
    with session_factory(task_engine)() as session:
        failure = session.scalar(select(models.JobEvaluationFailure))
        failure.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    assert evaluate_task.evaluate_pending_jobs()["failed"] == 1
    assert len(requests_seen) == 2
    with session_factory(task_engine)() as session:
        failure = session.scalar(select(models.JobEvaluationFailure))
        assert failure.attempts == 2
        assert failure.next_attempt_at - failure.last_attempt_at == 2 * first_backoff


def test_successful_retry_clears_the_failure_row(task_engine, requests_seen):
    seeded = _seed(task_engine, jobs=1)
    parsed_id = seeded["parsed_ids"][0]
    task_engine.set_handler(lambda req: httpx.Response(502, json={"error": "nope"}))
    evaluate_task.evaluate_pending_jobs()
    with session_factory(task_engine)() as session:
        failure = session.scalar(select(models.JobEvaluationFailure))
        failure.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()

    task_engine.set_handler(lambda req: httpx.Response(200, json=_decision(0.6)))
    result = evaluate_task.evaluate_parse_results([parsed_id])

    assert result["evaluated"] == 1
    with session_factory(task_engine)() as session:
        assert session.scalar(select(models.JobEvaluationFailure)) is None
        assert session.scalar(select(models.JobEvaluation)).match_probability == 0.6


def test_pair_is_given_up_after_max_attempts(task_engine, requests_seen, monkeypatch):
    seeded = _seed(task_engine, jobs=1)
    parsed_id, profile_id = seeded["parsed_ids"][0], seeded["profile_ids"][0]
    monkeypatch.setattr(
        evaluate_task, "get_settings", lambda: Settings(cors_origins=[], evaluate_max_attempts=2)
    )
    with session_factory(task_engine)() as session:
        session.add(
            models.JobEvaluationFailure(
                job_parse_result_id=parsed_id,
                candidate_profile_id=profile_id,
                attempts=2,
                next_attempt_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
        session.commit()

    assert evaluate_task.evaluate_pending_jobs()["pending"] == 0
    assert evaluate_task.evaluate_parse_results([parsed_id])["pending"] == 0
    assert requests_seen == []


def test_evaluate_pending_jobs_respects_limit(task_engine, requests_seen):
    _seed(task_engine, jobs=3)

    result = evaluate_task.evaluate_pending_jobs(limit=2)

    assert result["pending"] == 2
    assert result["evaluated"] == 2
    assert len(requests_seen) == 2


def test_evaluate_without_profile_raises(task_engine):
    _seed(task_engine, profiles=(), jobs=1)

    with pytest.raises(evaluate_task.NoCandidateProfile):
        evaluate_task.evaluate_pending_jobs()
    with pytest.raises(evaluate_task.NoCandidateProfile):
        evaluate_task.evaluate_parse_results([1])
