from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app import models
from app.services import timeline
from tests.conftest import ensure_source


def _job_event(session, probability, *, title="Job"):
    source = ensure_source(session)
    job = models.Job(link=f"https://example.com/{title}-{probability}", source=source)
    session.add(job)
    session.flush()
    return timeline.record_event(
        session,
        models.TimelineEvent.TYPE_JOB_EVALUATED,
        job_id=job.id,
        source_id=source.id,
        payload={"title": title, "match_probability": probability},
    )


def _seed(session, n):
    ids = []
    for i in range(n):
        event = timeline.record_event(session, "scrape_run", payload={"i": i})
        session.flush()
        ids.append(event.id)
    session.commit()
    return ids


def test_paging_in_both_directions(db_session):
    ids = _seed(db_session, 10)

    newest = timeline.page(db_session, limit=3)
    assert [e.id for e in newest.events] == ids[-3:]
    assert (newest.has_older, newest.has_newer) == (True, False)

    after = timeline.page(db_session, after_id=ids[2], limit=3)
    assert [e.id for e in after.events] == ids[3:6]
    assert (after.has_older, after.has_newer) == (True, True)

    before = timeline.page(db_session, before_id=ids[2], limit=5)
    assert [e.id for e in before.events] == ids[:2]
    assert (before.has_older, before.has_newer) == (False, True)

    around = timeline.page(db_session, around_id=ids[4], limit=2, context=2)
    assert [e.id for e in around.events] == ids[3:7]
    assert (around.has_older, around.has_newer) == (True, True)

    past_end = timeline.page(db_session, after_id=ids[-1])
    assert past_end.events == []
    assert (past_end.has_older, past_end.has_newer) == (True, False)


def test_around_zero_starts_at_the_beginning(db_session):
    ids = _seed(db_session, 3)
    result = timeline.page(db_session, around_id=0)
    assert [e.id for e in result.events] == ids
    assert (result.has_older, result.has_newer) == (False, False)


def test_mark_read_only_moves_forward_and_stops_at_newest(db_session):
    ids = _seed(db_session, 5)
    timeline.mark_read(db_session, ids[3])
    timeline.mark_read(db_session, ids[1])
    assert timeline.last_read_event_id(db_session) == ids[3]
    timeline.mark_read(db_session, ids[-1] + 100)
    assert timeline.last_read_event_id(db_session) == ids[-1]


def test_status_counts_unread_and_relevant(db_session):
    first = _seed(db_session, 1)[0]
    timeline.mark_read(db_session, first)
    _job_event(db_session, 0.9, title="good")
    _job_event(db_session, 0.2, title="bad")
    _seed(db_session, 1)

    result = timeline.status(db_session)
    assert result.last_read_id == first
    assert result.unread == 3
    assert result.unread_relevant == 1
    assert result.latest_id == first + 3


def test_event_survives_its_job_being_deleted(db_session):
    event = _job_event(db_session, 0.9, title="gone")
    db_session.commit()
    db_session.delete(db_session.get(models.Job, event.job_id))
    db_session.commit()

    db_session.expire_all()
    stored = db_session.scalars(select(models.TimelineEvent)).one()
    assert stored.job_id is None
    assert stored.payload["title"] == "gone"


def test_prune_only_removes_old_read_events(db_session):
    ids = _seed(db_session, 3)
    old = datetime.now(UTC) - timedelta(days=200)
    for event in db_session.scalars(select(models.TimelineEvent)):
        event.occurred_at = old
    db_session.commit()
    timeline.mark_read(db_session, ids[1])

    assert timeline.prune_read_events(db_session, datetime.now(UTC) - timedelta(days=90)) == 2
    remaining = db_session.scalars(select(models.TimelineEvent.id)).all()
    assert remaining == [ids[2]]


def test_api_events_status_and_read(client, engine):
    from app.db import session_factory

    with session_factory(engine)() as session:
        good = _job_event(session, 0.9, title="good")
        bad = _job_event(session, 0.1, title="bad")
        session.commit()
        good_id, bad_id = good.id, bad.id

    status = client.get("/api/timeline/status").json()
    assert status == {"latest_id": bad_id, "last_read_id": 0, "unread": 2, "unread_relevant": 1}

    page = client.get("/api/timeline/events", params={"around_id": 0}).json()
    assert [e["id"] for e in page["events"]] == [good_id, bad_id]
    assert [e["relevant"] for e in page["events"]] == [True, False]
    assert page["events"][0]["relevance"] > 0
    assert (page["has_older"], page["has_newer"]) == (False, False)

    status = client.put("/api/timeline/read", json={"event_id": good_id}).json()
    assert status["last_read_id"] == good_id
    assert (status["unread"], status["unread_relevant"]) == (1, 0)


def test_api_times_are_utc(client, engine):
    from app.db import session_factory

    with session_factory(engine)() as session:
        timeline.record_event(session, "scrape_run")
        session.commit()
    (event,) = client.get("/api/timeline/events").json()["events"]
    assert event["occurred_at"].endswith(("Z", "+00:00"))


def test_api_job_events_carry_live_tag_evaluation_and_application(client, engine):
    from app.db import session_factory

    with session_factory(engine)() as session:
        profile = models.CandidateProfile(content="Dev")
        company = models.Company(name="ACME", normalized_name="acme", tag="favourite")
        job = models.Job(link="https://example.com/live", source=ensure_source(session))
        parsed = models.JobParseResult(job=job, title="Dev", company=company)
        session.add_all([profile, company, job, parsed])
        session.flush()
        evaluation = models.JobEvaluation(
            job_parse_result=parsed, candidate_profile=profile, match_probability=0.9
        )
        session.add(evaluation)
        session.flush()
        timeline.record_job_evaluated(session, parsed, evaluation)
        session.commit()
        evaluation_id, company_id, parsed_id = evaluation.id, company.id, parsed.id

    (event,) = client.get("/api/timeline/events").json()["events"]
    assert event["company_id"] == company_id
    assert event["company_tag"] == "favourite"
    assert event["evaluation_id"] == evaluation_id
    assert event["application_id"] is None

    with session_factory(engine)() as session:
        application = models.Application(
            job_parse_result_id=parsed_id, job_evaluation_id=evaluation_id
        )
        session.add(application)
        session.get(models.Company, company_id).tag = "avoid"
        session.commit()
        application_id = application.id

    (event,) = client.get("/api/timeline/events").json()["events"]
    assert event["company_tag"] == "avoid"
    assert event["application_id"] == application_id
