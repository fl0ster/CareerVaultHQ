from datetime import UTC, date, datetime, timedelta

from app.models import (
    Application,
    CandidateProfile,
    Company,
    GeneratedCV,
    Job,
    JobEvaluation,
    JobParseResult,
    WorkHistoryEntry,
)
from tests.conftest import ensure_source

BASE = "/api/applications"


def seed_evaluation(db_session, i=0, profile=None) -> JobEvaluation:
    job = Job(link=f"https://example.com/jobs/{i}", source=ensure_source(db_session))
    parsed = JobParseResult(
        job=job,
        title=f"Title {i}",
        description="Desc",
        company=Company(name=f"Acme {i}", normalized_name=f"acme {i}"),
    )
    profile = profile or CandidateProfile(content="p")
    evaluation = JobEvaluation(
        job_parse_result=parsed, candidate_profile=profile, match_probability=0.8
    )
    db_session.add_all([job, parsed, evaluation])
    db_session.commit()
    return evaluation


def seed_cv_inputs(client, db_session):
    db_session.add(
        WorkHistoryEntry(date_start=date(2020, 1, 1), employer="Acme", role="Dev", tech=[])
    )
    db_session.commit()
    assert (
        client.put(
            "/api/candidate-details", json={"first_name": "Jane", "last_name": "Doe"}
        ).status_code
        == 200
    )


def _cv_jobs(fake_queue):
    return [j for j in fake_queue.jobs if j.func_name.endswith("generate_cv")]


def test_statuses_are_seeded_and_extensible(client):
    keys = [s["key"] for s in client.get(f"{BASE}/statuses").json()]
    assert keys == ["SHORTLISTED", "APPLIED", "INTERVIEW", "OFFER", "REJECTED"]

    res = client.post(f"{BASE}/statuses", json={"key": "ghosted"})
    assert res.status_code == 201
    assert res.json()["key"] == "GHOSTED" and res.json()["label"] == "Ghosted"
    assert client.post(f"{BASE}/statuses", json={"key": "GHOSTED"}).status_code == 409
    assert [s["key"] for s in client.get(f"{BASE}/statuses").json()][-1] == "GHOSTED"


def test_create_application_queues_cv(client, db_session, fake_queue):
    evaluation = seed_evaluation(db_session)
    seed_cv_inputs(client, db_session)

    res = client.post(
        BASE, json={"job_evaluation_id": evaluation.id, "notes": "referral", "status_note": "x"}
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["notes"] == "referral"
    assert body["status"]["key"] == "SHORTLISTED"
    assert [(e["status"]["key"], e["note"]) for e in body["events"]] == [("SHORTLISTED", "x")]
    assert body["job"]["title"] == "Title 0" and body["job"]["company"] == "Acme 0"
    assert body["job"]["company_id"] is not None and body["job"]["company_notes"] == ""

    # Company notes edited on the company show up on its applications.
    client.patch(f"/api/companies/{body['job']['company_id']}", json={"notes": "met at a meetup"})
    assert client.get(f"{BASE}/{body['id']}").json()["job"]["company_notes"] == "met at a meetup"
    assert body["job"]["company_tag"] is None
    client.patch(f"/api/companies/{body['job']['company_id']}", json={"tag": "avoid"})
    assert client.get(f"{BASE}/{body['id']}").json()["job"]["company_tag"] == "avoid"
    assert body["evaluation"]["match_probability"] == 0.8
    assert body["cv"]["status"] == "queued"
    assert [j.args for j in _cv_jobs(fake_queue)] == [(body["cv"]["id"],)]

    # One application per job, even through an evaluation against another profile.
    again = client.post(BASE, json={"job_evaluation_id": evaluation.id})
    assert again.status_code == 409
    other = JobEvaluation(
        job_parse_result_id=evaluation.job_parse_result_id,
        candidate_profile=CandidateProfile(content="new"),
        match_probability=0.3,
    )
    db_session.add(other)
    db_session.commit()
    assert client.post(BASE, json={"job_evaluation_id": other.id}).status_code == 409

    jobs = client.get("/api/jobs").json()["items"]
    assert [j["application_id"] for j in jobs] == [body["id"]]
    assert client.get(f"/api/jobs/{body['job']['id']}").json()["application_id"] == body["id"]


def test_create_application_validation(client, db_session, fake_queue):
    assert client.post(BASE, json={"job_evaluation_id": 999}).status_code == 404
    evaluation = seed_evaluation(db_session)
    res = client.post(BASE, json={"job_evaluation_id": evaluation.id})
    assert res.status_code == 400 and "work history" in res.json()["detail"]
    seed_cv_inputs(client, db_session)
    bad = client.post(BASE, json={"job_evaluation_id": evaluation.id, "status": "NOPE"})
    assert bad.status_code == 422
    assert db_session.query(Application).count() == 0

    res = client.post(BASE, json={"job_evaluation_id": evaluation.id, "status": None})
    assert res.status_code == 201
    assert res.json()["status"] is None and res.json()["events"] == []


def test_create_application_when_queue_is_down(client, db_session, fake_queue, monkeypatch):
    evaluation = seed_evaluation(db_session)
    seed_cv_inputs(client, db_session)

    def boom(*args, **kwargs):
        raise ConnectionError("redis down")

    monkeypatch.setattr(fake_queue, "enqueue", boom)
    res = client.post(BASE, json={"job_evaluation_id": evaluation.id})
    assert res.status_code == 201
    assert res.json()["cv"]["status"] == "failed"


def test_events_notes_and_listing(client, db_session):
    seed_cv_inputs(client, db_session)
    profile = CandidateProfile(content="p")
    a = client.post(BASE, json={"job_evaluation_id": seed_evaluation(db_session, 0, profile).id})
    b = client.post(BASE, json={"job_evaluation_id": seed_evaluation(db_session, 1, profile).id})
    a_id, b_id = a.json()["id"], b.json()["id"]

    res = client.post(f"{BASE}/{a_id}/events", json={"status": "interview", "note": "Tue 10:00"})
    assert res.status_code == 201
    assert res.json()["status"]["key"] == "INTERVIEW"
    assert [e["status"]["key"] for e in res.json()["events"]] == ["SHORTLISTED", "INTERVIEW"]

    # A back-dated state does not become the current one.
    past = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    res = client.post(f"{BASE}/{a_id}/events", json={"status": "OFFER", "occurred_at": past})
    assert res.json()["status"]["key"] == "INTERVIEW"
    assert res.json()["events"][0]["status"]["key"] == "OFFER"
    offer_id = res.json()["events"][0]["id"]

    res = client.patch(f"{BASE}/{a_id}/events/{offer_id}", json={"note": "verbal"})
    assert res.json()["events"][0]["note"] == "verbal"
    res = client.delete(f"{BASE}/{a_id}/events/{offer_id}")
    assert len(res.json()["events"]) == 2
    assert client.delete(f"{BASE}/{a_id}/events/{offer_id}").status_code == 404
    assert client.post(f"{BASE}/{a_id}/events", json={"status": "X"}).status_code == 422

    assert client.patch(f"{BASE}/{b_id}", json={"notes": "hello"}).json()["notes"] == "hello"

    page = client.get(BASE).json()
    assert [i["id"] for i in page["items"]] == [b_id, a_id]
    assert page["total"] == 2
    filtered = client.get(BASE, params={"status": "interview"}).json()
    assert [i["id"] for i in filtered["items"]] == [a_id]

    assert client.delete(f"{BASE}/{b_id}").status_code == 204
    assert client.get(f"{BASE}/{b_id}").status_code == 404
    assert db_session.query(GeneratedCV).count() == 2  # CVs outlive the application


def test_regenerate_cv(client, db_session, fake_queue):
    seed_cv_inputs(client, db_session)
    app_id = client.post(BASE, json={"job_evaluation_id": seed_evaluation(db_session).id}).json()[
        "id"
    ]
    assert client.post(f"{BASE}/{app_id}/cv").status_code == 409  # first one still queued

    cv = db_session.query(GeneratedCV).one()
    cv.status = GeneratedCV.STATUS_FAILED
    db_session.commit()
    res = client.post(f"{BASE}/{app_id}/cv")
    assert res.status_code == 200
    assert res.json()["cv"]["id"] != cv.id and res.json()["cv"]["status"] == "queued"
    assert len(_cv_jobs(fake_queue)) == 2


def test_event_dates_are_stored_in_utc(client, db_session):
    seed_cv_inputs(client, db_session)
    app_id = client.post(BASE, json={"job_evaluation_id": seed_evaluation(db_session).id}).json()[
        "id"
    ]
    res = client.post(
        f"{BASE}/{app_id}/events",
        json={"status": "INTERVIEW", "occurred_at": "2030-01-01T12:00:00+02:00"},
    )
    assert res.json()["events"][-1]["occurred_at"].startswith("2030-01-01T10:00:00")
