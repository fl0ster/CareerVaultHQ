from datetime import UTC, date, datetime, timedelta

import pytest

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
from app.services.candidate_profile import _work_history_payload, work_history_id
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
    evaluation = JobEvaluation(job_parse_result=parsed, candidate_profile=profile, match_probability=0.8)
    db_session.add_all([job, parsed, evaluation])
    db_session.commit()
    return evaluation


def seed_cv_inputs(client, db_session):
    db_session.add(WorkHistoryEntry(date_start=date(2020, 1, 1), employer="Acme", role="Dev", tech=[]))
    db_session.commit()
    assert client.put("/api/candidate-details", json={"first_name": "Jane", "last_name": "Doe"}).status_code == 200


def _cv_jobs(fake_queue):
    return [j for j in fake_queue.jobs if j.func_name.endswith("generate_cv")]


def test_statuses_are_seeded_and_extensible(client):
    keys = [s["key"] for s in client.get(f"{BASE}/statuses").json()]
    assert keys == ["SHORTLISTED", "APPLIED", "INTERVIEW", "OFFER", "REJECTED", "CLOSED", "ACCEPTED", "DECLINED"]

    res = client.post(f"{BASE}/statuses", json={"key": "ghosted"})
    assert res.status_code == 201
    assert res.json()["key"] == "GHOSTED" and res.json()["label"] == "Ghosted"
    assert client.post(f"{BASE}/statuses", json={"key": "GHOSTED"}).status_code == 409
    assert [s["key"] for s in client.get(f"{BASE}/statuses").json()][-1] == "GHOSTED"


def test_create_application_queues_cv(client, db_session, fake_queue):
    evaluation = seed_evaluation(db_session)
    seed_cv_inputs(client, db_session)

    res = client.post(BASE, json={"job_evaluation_id": evaluation.id, "notes": "referral", "status_note": "x"})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["notes"] == "referral"
    # Creating the application accepts the job, so it leaves the Jobs inbox.
    assert client.get("/api/jobs/inbox").json()["count"] == 0
    assert client.get("/api/jobs").json()["items"][0]["decision"] == "accepted"
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
    app_id = client.post(BASE, json={"job_evaluation_id": seed_evaluation(db_session).id}).json()["id"]
    assert client.post(f"{BASE}/{app_id}/cv").status_code == 409  # first one still queued

    cv = db_session.query(GeneratedCV).one()
    cv.status = GeneratedCV.STATUS_FAILED
    db_session.commit()
    res = client.post(f"{BASE}/{app_id}/cv")
    assert res.status_code == 200
    assert res.json()["cv"]["id"] != cv.id and res.json()["cv"]["status"] == "queued"
    assert len(_cv_jobs(fake_queue)) == 2


def test_cv_overrides_are_saved_and_used_by_the_next_cv(client, db_session, fake_queue):
    seed_cv_inputs(client, db_session)
    app_id = client.post(BASE, json={"job_evaluation_id": seed_evaluation(db_session).id}).json()["id"]
    assert client.get(f"{BASE}/{app_id}").json()["cv_overrides"] is None

    res = client.patch(
        f"{BASE}/{app_id}",
        json={
            "cv_overrides": {
                "headline_role": "  Mobile Lead ",
                "summary": " ",
                "roles": {"7": "drop", "3": "early"},
                "contexts": {"3": " Did things. ", "4": "  "},
                "techs": {"3": [" Go ", "Go", "", "Rust"], "5": []},
            }
        },
    )
    assert res.status_code == 200
    saved = res.json()["cv_overrides"]
    assert saved["headline_role"] == "Mobile Lead"
    assert saved["summary"] is None  # blank: left out
    assert saved["roles"] == {"3": "early", "7": "drop"}
    assert saved["contexts"] == {"3": "Did things."}
    assert saved["techs"] == {"3": ["Go", "Rust"], "5": []}  # trimmed, deduplicated; "none" kept
    assert res.json()["cv"]["overrides"] is None  # the current CV was made without them

    assert client.patch(f"{BASE}/{app_id}", json={"cv_overrides": {"roles": {"1": "maybe"}}}).status_code == 422

    cv = db_session.query(GeneratedCV).one()
    cv.status = GeneratedCV.STATUS_FINISHED
    db_session.commit()
    new_cv = client.post(f"{BASE}/{app_id}/cv").json()["cv"]
    assert new_cv["overrides"]["headline_role"] == "Mobile Lead"
    assert new_cv["overrides"]["roles"] == {"3": "early", "7": "drop"}

    # Removing every edit (or sending only blanks) clears them.
    assert client.patch(f"{BASE}/{app_id}", json={"cv_overrides": {"summary": ""}}).json()["cv_overrides"] is None
    client.patch(f"{BASE}/{app_id}", json={"cv_overrides": {"summary": "x"}})
    assert client.patch(f"{BASE}/{app_id}", json={"cv_overrides": None}).json()["cv_overrides"] is None


def _tailor_jobs(fake_queue):
    return [j for j in fake_queue.jobs if j.func_name.endswith("tailor_moved_role")]


def test_tailoring_a_moved_role_is_queued_and_kept_apart_from_the_edits(client, db_session, fake_queue):
    from app.config import get_settings
    from app.main import app as fastapi_app

    settings = fastapi_app.dependency_overrides[get_settings]()
    fastapi_app.dependency_overrides[get_settings] = lambda: settings.model_copy(update={"openrouter_api_key": "k"})
    seed_cv_inputs(client, db_session)
    pid = db_session.query(WorkHistoryEntry).one().id
    app_id = client.post(BASE, json={"job_evaluation_id": seed_evaluation(db_session).id}).json()["id"]
    client.patch(f"{BASE}/{app_id}", json={"cv_overrides": {"roles": {str(pid): "main"}}})

    # Queued for the worker, not run in the request.
    res = client.post(f"{BASE}/{app_id}/cv/tailor", json={"work_history_id": pid, "placement": "main"})
    assert res.status_code == 202
    made = res.json()["cv_overrides"]["tailored"][str(pid)]["main"]
    assert made["status"] == "queued" and made["context"] is None
    [job] = _tailor_jobs(fake_queue)
    assert job.args == (app_id, pid, "main") and job.id == made["rq_job_id"]
    assert res.json()["cv_overrides"]["roles"] == {str(pid): "main"}  # the edits are untouched
    # Asking again while it is queued queues nothing more.
    client.post(f"{BASE}/{app_id}/cv/tailor", json={"work_history_id": pid, "placement": "main"})
    assert len(_tailor_jobs(fake_queue)) == 1

    # Saving edits keeps the tailoring (a client cannot set it); removing every edit drops it.
    res = client.patch(
        f"{BASE}/{app_id}",
        json={"cv_overrides": {"summary": "Mine.", "tailored": {"9": {"main": {"context": "forged"}}}}},
    )
    assert set(res.json()["cv_overrides"]["tailored"]) == {str(pid)}
    assert res.json()["cv_overrides"]["roles"] == {}
    assert client.patch(f"{BASE}/{app_id}", json={"cv_overrides": None}).json()["cv_overrides"] is None

    assert client.post(f"{BASE}/{app_id}/cv/tailor", json={"work_history_id": 999, "placement": "main"}).status_code == 404
    assert client.post(f"{BASE}/{app_id}/cv/tailor", json={"work_history_id": pid, "placement": "drop"}).status_code == 422
    fastapi_app.dependency_overrides[get_settings] = lambda: settings.model_copy(update={"openrouter_api_key": ""})
    assert client.post(f"{BASE}/{app_id}/cv/tailor", json={"work_history_id": pid, "placement": "main"}).status_code == 503


def test_cv_edits_and_a_tailoring_result_do_not_undo_each_other(client, db_session, engine):
    """The API and the worker both rewrite ``cv_overrides``: each must build on what is
    stored when it writes, not on what it read earlier."""
    from app.db import session_factory
    from app.services.applications import set_cv_edits, store_tailored

    seed_cv_inputs(client, db_session)
    app_id = client.post(BASE, json={"job_evaluation_id": seed_evaluation(db_session).id}).json()["id"]
    client.patch(f"{BASE}/{app_id}", json={"cv_overrides": {"roles": {"7": "main"}}})
    with session_factory(engine)() as api, session_factory(engine)() as worker:
        store_tailored(worker, worker.get(Application, app_id), 7, "main", {"status": "queued"})
        worker.commit()
        stale = api.get(Application, app_id)  # the API reads it while the role is queued
        assert stale.cv_overrides["tailored"]["7"]["main"]["status"] == "queued"

        done = {"status": "done", "context": "Tailored.", "tech": []}
        assert store_tailored(worker, worker.get(Application, app_id), 7, "main", done, expect="queued")
        worker.commit()
        set_cv_edits(api, stale, {"roles": {"7": "main"}, "summary": "Mine."})
        api.commit()

        # The worker finishing after the API read it changes nothing more.
        assert not store_tailored(worker, worker.get(Application, app_id), 7, "main", {"status": "failed"}, expect="queued")
        worker.commit()

    stored = client.get(f"{BASE}/{app_id}").json()["cv_overrides"]
    assert stored["summary"] == "Mine."
    assert stored["tailored"]["7"]["main"]["status"] == "done"


def test_event_dates_are_stored_in_utc(client, db_session):
    seed_cv_inputs(client, db_session)
    app_id = client.post(BASE, json={"job_evaluation_id": seed_evaluation(db_session).id}).json()["id"]
    res = client.post(
        f"{BASE}/{app_id}/events",
        json={"status": "INTERVIEW", "occurred_at": "2030-01-01T12:00:00+02:00"},
    )
    assert res.json()["events"][-1]["occurred_at"].startswith("2030-01-01T10:00:00")


def test_company_application_stats(client, db_session):
    seed_cv_inputs(client, db_session)
    profile = CandidateProfile(content="p")
    flows = [
        ["APPLIED"],
        ["APPLIED", "INTERVIEW"],
        ["APPLIED", "INTERVIEW", "REJECTED"],
        ["INTERVIEW", "OFFER"],
        [],
    ]
    company_ids = []
    for i, flow in enumerate(flows):
        evaluation = seed_evaluation(db_session, i, profile)
        company_ids.append(evaluation.job_parse_result.company_id)
        app_id = client.post(BASE, json={"job_evaluation_id": evaluation.id}).json()["id"]
        for key in flow:
            client.post(f"{BASE}/{app_id}/events", json={"status": key})

    stats = client.get("/api/companies/application-stats").json()
    # The seeded work history adds its employer with the positions held there.
    career = {company: counts for company, counts in stats.items() if counts == {"CAREER": 1}}
    assert len(career) == 1
    assert {company: counts for company, counts in stats.items() if company not in career} == {
        str(company_ids[0]): {"APPLIED": 1},
        str(company_ids[1]): {"INTERVIEW": 1},
        str(company_ids[2]): {"REJECTED": 1},
        str(company_ids[3]): {"OFFER": 1},
    }


def test_shortlisted_is_only_set_at_creation(client, db_session):
    seed_cv_inputs(client, db_session)
    evaluation = seed_evaluation(db_session)
    app_id = client.post(BASE, json={"job_evaluation_id": evaluation.id}).json()["id"]
    shortlisted_id = client.get(f"{BASE}/{app_id}").json()["events"][0]["id"]

    assert client.post(f"{BASE}/{app_id}/events", json={"status": "shortlisted"}).status_code == 422
    assert client.delete(f"{BASE}/{app_id}/events/{shortlisted_id}").status_code == 422
    url = f"{BASE}/{app_id}/events/{shortlisted_id}"
    assert client.patch(url, json={"status": "APPLIED"}).status_code == 422

    res = client.patch(url, json={"status": "SHORTLISTED", "note": "nice"})
    assert res.status_code == 200 and res.json()["events"][0]["note"] == "nice"

    res = client.post(f"{BASE}/{app_id}/events", json={"status": "APPLIED"})
    applied_id = res.json()["events"][1]["id"]
    res = client.patch(f"{BASE}/{app_id}/events/{applied_id}", json={"status": "SHORTLISTED"})
    assert res.status_code == 422


@pytest.mark.parametrize("final", ["REJECTED", "OFFER", "CLOSED"])
def test_final_state_blocks_new_states_until_removed(client, db_session, final):
    seed_cv_inputs(client, db_session)
    evaluation = seed_evaluation(db_session)
    app_id = client.post(BASE, json={"job_evaluation_id": evaluation.id}).json()["id"]
    events = client.post(f"{BASE}/{app_id}/events", json={"status": final}).json()["events"]
    assert client.post(f"{BASE}/{app_id}/events", json={"status": "APPLIED"}).status_code == 409

    rejected_id = events[-1]["id"]
    res = client.patch(f"{BASE}/{app_id}/events/{rejected_id}", json={"note": "ghosted"})
    assert res.status_code == 200
    assert client.delete(f"{BASE}/{app_id}/events/{rejected_id}").status_code == 200
    assert client.post(f"{BASE}/{app_id}/events", json={"status": "APPLIED"}).status_code == 201


def test_applied_only_once_and_after_shortlisted(client, db_session):
    seed_cv_inputs(client, db_session)
    profile = CandidateProfile(content="p")
    a = client.post(BASE, json={"job_evaluation_id": seed_evaluation(db_session, 0, profile).id})
    a_id = a.json()["id"]
    events = f"{BASE}/{a_id}/events"
    assert client.post(events, json={"status": "APPLIED"}).status_code == 201
    assert client.post(events, json={"status": "APPLIED"}).status_code == 409
    res = client.post(events, json={"status": "INTERVIEW"})
    interview_id = res.json()["events"][-1]["id"]
    res = client.patch(f"{events}/{interview_id}", json={"status": "APPLIED"})
    assert res.status_code == 409

    b = client.post(BASE, json={"job_evaluation_id": seed_evaluation(db_session, 1, profile).id})
    events = f"{BASE}/{b.json()['id']}/events"
    assert client.post(events, json={"status": "INTERVIEW"}).status_code == 201
    assert client.post(events, json={"status": "APPLIED"}).status_code == 409


def _rounds(body):
    """(held interview rounds, titles of the planned ones)."""
    held = [e for e in body["events"] if e["status"]["key"] == "INTERVIEW" and not e["stage_entry"]]
    return len(held), [e["title"] for e in body["planned_events"]]


def _new_application(client, db_session, *states):
    seed_cv_inputs(client, db_session)
    evaluation = seed_evaluation(db_session)
    app_id = client.post(BASE, json={"job_evaluation_id": evaluation.id}).json()["id"]
    for key in states:
        client.post(f"{BASE}/{app_id}/events", json={"status": key})
    return app_id


def test_interview_rounds_are_planned_and_resized(client, db_session):
    app_id = _new_application(client, db_session, "APPLIED", "INTERVIEW")
    url = f"{BASE}/{app_id}"

    body = client.patch(url, json={"interview_rounds": 5}).json()
    assert _rounds(body) == (0, [""] * 5)
    # Planned rounds are never the current state.
    assert body["status"]["key"] == "INTERVIEW" and body["notes"] == ""

    first = body["planned_events"][0]["id"]
    body = client.patch(f"{url}/events/{first}", json={"title": "Culture match", "duration_minutes": 60}).json()
    assert body["planned_events"][0]["duration_minutes"] == 60

    # Shrinking drops rounds from the end; 0 drops every planned one.
    assert _rounds(client.patch(url, json={"interview_rounds": 3}).json()) == (
        0,
        ["Culture match", "", ""],
    )
    assert _rounds(client.patch(url, json={"interview_rounds": 0}).json()) == (0, [])
    client.post(f"{url}/events", json={"status": "INTERVIEW"})
    client.post(f"{url}/events", json={"status": "INTERVIEW"})
    assert client.patch(url, json={"interview_rounds": 1}).status_code == 422
    # Notes alone leave the rounds alone.
    client.patch(url, json={"interview_rounds": 4})
    body = client.patch(url, json={"notes": "n"}).json()
    assert body["notes"] == "n" and _rounds(body) == (2, ["", ""])


def test_recording_an_interview_holds_the_next_round(client, db_session):
    app_id = _new_application(client, db_session, "APPLIED")
    url = f"{BASE}/{app_id}"
    body = client.patch(url, json={"interview_rounds": 2}).json()
    first, second = (e["id"] for e in body["planned_events"])
    # Planned rounds are not interviews yet (current state, company stats).
    assert body["status"]["key"] == "APPLIED"
    stats = client.get("/api/companies/application-stats").json()
    assert stats[str(body["job"]["company_id"])] == {"APPLIED": 1}
    client.patch(f"{url}/events/{first}", json={"title": "HR", "note": "plan note"})

    # The first interview only enters the stage: every round is still planned.
    body = client.post(f"{url}/events", json={"status": "INTERVIEW"}).json()
    entry = body["events"][-1]
    assert body["status"]["key"] == "INTERVIEW" and entry["stage_entry"]
    assert _rounds(body) == (0, ["HR", ""])

    body = client.post(f"{url}/events", json={"status": "INTERVIEW"}).json()
    held = body["events"][-1]
    assert (held["id"], held["title"], held["note"]) == (first, "HR", "plan note")
    assert not held["stage_entry"]
    assert held["occurred_at"] is not None
    assert [e["id"] for e in body["planned_events"]] == [second]

    # A specific round can be held; without planned rounds an interview adds one.
    body = client.patch(f"{url}/events/{second}", json={"planned": False}).json()
    assert _rounds(body) == (2, [])
    body = client.post(f"{url}/events", json={"status": "INTERVIEW"}).json()
    assert _rounds(body) == (3, [])

    # Deleting a held round makes it planned again; deleting a planned one drops it.
    extra = body["events"][-1]["id"]
    body = client.delete(f"{url}/events/{extra}").json()
    assert [e["id"] for e in body["planned_events"]] == [extra]
    body = client.delete(f"{url}/events/{extra}").json()
    assert _rounds(body) == (2, [])

    # Removing the stage entry drops it instead of planning it.
    body = client.delete(f"{url}/events/{entry['id']}").json()
    assert entry["id"] not in [e["id"] for e in body["events"] + body["planned_events"]]
    assert _rounds(body) == (2, [])


def test_entering_the_interview_stage_holds_no_round(client, db_session):
    app_id = _new_application(client, db_session, "APPLIED")
    url = f"{BASE}/{app_id}"
    client.patch(url, json={"interview_rounds": 2})

    body = client.post(f"{url}/events", json={"status": "INTERVIEW"}).json()
    assert body["status"]["key"] == "INTERVIEW" and _rounds(body) == (0, ["", ""])

    body = client.delete(f"{url}/events/{body['events'][-1]['id']}").json()
    assert body["status"]["key"] == "APPLIED" and _rounds(body) == (0, ["", ""])


def test_picking_applied_again_leaves_the_interview_stage(client, db_session):
    app_id = _new_application(client, db_session, "APPLIED")
    url = f"{BASE}/{app_id}"
    client.patch(url, json={"interview_rounds": 2})
    client.post(f"{url}/events", json={"status": "INTERVIEW"})
    body = client.post(f"{url}/events", json={"status": "INTERVIEW"}).json()
    assert _rounds(body) == (1, [""])

    res = client.post(f"{url}/events", json={"status": "APPLIED"})
    assert res.status_code == 201
    body = res.json()
    assert body["status"]["key"] == "APPLIED" and _rounds(body) == (0, ["", ""])
    assert [e["status"]["key"] for e in body["events"]] == ["SHORTLISTED", "APPLIED"]
    # Outside the interview stage APPLIED still cannot be recorded twice.
    assert client.post(f"{url}/events", json={"status": "APPLIED"}).status_code == 409


def test_removing_applied_leaves_the_interview_stage(client, db_session):
    app_id = _new_application(client, db_session, "APPLIED")
    url = f"{BASE}/{app_id}"
    client.patch(url, json={"interview_rounds": 2})
    client.post(f"{url}/events", json={"status": "INTERVIEW"})
    body = client.post(f"{url}/events", json={"status": "INTERVIEW"}).json()
    applied = next(e["id"] for e in body["events"] if e["status"]["key"] == "APPLIED")

    body = client.delete(f"{url}/events/{applied}").json()
    assert body["status"]["key"] == "SHORTLISTED" and _rounds(body) == (0, ["", ""])
    assert [e["status"]["key"] for e in body["events"]] == ["SHORTLISTED"]


@pytest.mark.parametrize("final", ["OFFER", "REJECTED"])
def test_removing_applied_drops_every_later_state(client, db_session, final):
    app_id = _new_application(client, db_session, "APPLIED")
    url = f"{BASE}/{app_id}"
    client.patch(url, json={"interview_rounds": 2})
    client.post(f"{url}/events", json={"status": "INTERVIEW"})
    client.post(f"{url}/events", json={"status": "INTERVIEW"})
    body = client.post(f"{url}/events", json={"status": final}).json()
    applied = next(e["id"] for e in body["events"] if e["status"]["key"] == "APPLIED")

    body = client.delete(f"{url}/events/{applied}").json()
    assert body["status"]["key"] == "SHORTLISTED" and _rounds(body) == (0, ["", ""])
    assert [e["status"]["key"] for e in body["events"]] == ["SHORTLISTED"]


def test_final_state_keeps_planned_rounds_but_blocks_them(client, db_session):
    app_id = _new_application(client, db_session, "APPLIED", "INTERVIEW")
    url = f"{BASE}/{app_id}"
    planned = client.patch(url, json={"interview_rounds": 3}).json()["planned_events"][0]["id"]

    body = client.post(f"{url}/events", json={"status": "REJECTED"}).json()
    assert body["status"]["key"] == "REJECTED" and len(body["planned_events"]) == 3
    assert client.post(f"{url}/events", json={"status": "INTERVIEW"}).status_code == 409
    assert client.patch(f"{url}/events/{planned}", json={"planned": False}).status_code == 409


def test_manual_events_are_marked_manual(client, db_session):
    evaluation = seed_evaluation(db_session)
    seed_cv_inputs(client, db_session)
    application = client.post(BASE, json={"job_evaluation_id": evaluation.id}).json()

    body = client.post(f"{BASE}/{application['id']}/events", json={"status": "APPLIED"}).json()

    assert [e["source"] for e in body["events"]] == ["manual", "manual"]


def test_listing_is_newest_first_regardless_of_state(client, db_session):
    seed_cv_inputs(client, db_session)
    evaluations = [seed_evaluation(db_session, i) for i in range(3)]
    ids = [client.post(BASE, json={"job_evaluation_id": e.id}).json()["id"] for e in evaluations]
    client.post(f"{BASE}/{ids[0]}/events", json={"status": "APPLIED"})
    client.post(f"{BASE}/{ids[0]}/events", json={"status": "OFFER"})
    client.post(f"{BASE}/{ids[1]}/events", json={"status": "REJECTED"})

    body = client.get(BASE).json()
    assert [a["id"] for a in body["items"]] == ids[::-1]


def test_create_application_queues_enrichment(client, db_session, fake_queue):
    """Interview steps and technologies are only extracted once the job is shortlisted."""
    seed_cv_inputs(client, db_session)
    evaluation = seed_evaluation(db_session)

    assert client.post(BASE, json={"job_evaluation_id": evaluation.id}).status_code == 201

    enrich = [j for j in fake_queue.jobs if j.func_name == "app.tasks.parse.enrich.enrich_job"]
    assert [j.args for j in enrich] == [(evaluation.job_parse_result_id,)]


def test_parsed_interview_steps_become_planned_rounds(client, db_session):
    seed_cv_inputs(client, db_session)
    evaluation = seed_evaluation(db_session)
    evaluation.job_parse_result.interview_steps = [
        {"number": 2, "title": "Technical interview", "duration_minutes": None},
        {"number": 1, "title": "HR call", "duration_minutes": 30},
    ]
    db_session.commit()

    body = client.post(BASE, json={"job_evaluation_id": evaluation.id}).json()

    planned = body["planned_events"]
    assert [(e["title"], e["duration_minutes"]) for e in planned] == [
        ("HR call", 30),
        ("Technical interview", None),
    ]
    assert all(e["status"]["key"] == "INTERVIEW" for e in planned)
    assert [e["status"]["key"] for e in body["events"]] == ["SHORTLISTED"]


def test_held_parsed_round_comes_after_applied(client, db_session):
    """A round planned from the job description and then held lands after APPLIED."""
    seed_cv_inputs(client, db_session)
    evaluation = seed_evaluation(db_session)
    evaluation.job_parse_result.interview_steps = [{"number": 1, "title": "HR call"}]
    db_session.commit()
    app_id = client.post(BASE, json={"job_evaluation_id": evaluation.id}).json()["id"]
    assert client.post(f"{BASE}/{app_id}/events", json={"status": "APPLIED"}).status_code == 201

    res = client.post(f"{BASE}/{app_id}/events", json={"status": "INTERVIEW"})
    assert res.status_code == 201
    expected = ["SHORTLISTED", "APPLIED", "INTERVIEW"]
    assert [e["status"]["key"] for e in res.json()["events"]] == expected
    assert res.json()["status"]["key"] == "INTERVIEW"
    body = client.get(f"{BASE}/{app_id}").json()
    assert [e["status"]["key"] for e in body["events"]] == expected


def test_states_cannot_be_dated_before_applied(client, db_session):
    seed_cv_inputs(client, db_session)
    app_id = client.post(BASE, json={"job_evaluation_id": seed_evaluation(db_session).id}).json()["id"]
    url = f"{BASE}/{app_id}/events"
    now = datetime.now(UTC)
    applied = client.post(url, json={"status": "APPLIED", "occurred_at": now.isoformat()})
    applied_id = next(e["id"] for e in applied.json()["events"] if e["status"]["key"] == "APPLIED")

    before = (now - timedelta(days=1)).isoformat()
    res = client.post(url, json={"status": "INTERVIEW", "occurred_at": before})
    assert res.status_code == 422

    after = (now + timedelta(hours=1)).isoformat()
    res = client.post(url, json={"status": "INTERVIEW", "occurred_at": after})
    assert res.status_code == 201
    interview_id = next(e["id"] for e in res.json()["events"] if e["status"]["key"] == "INTERVIEW")

    # Moving the interview before APPLIED, or APPLIED after the interview, is refused.
    assert client.patch(f"{url}/{interview_id}", json={"occurred_at": before}).status_code == 422
    later = (now + timedelta(days=1)).isoformat()
    assert client.patch(f"{url}/{applied_id}", json={"occurred_at": later}).status_code == 422
    keys = [e["status"]["key"] for e in client.get(f"{BASE}/{app_id}").json()["events"]]
    assert keys == ["SHORTLISTED", "APPLIED", "INTERVIEW"]


def test_rounds_and_applied_cannot_be_dated_before_shortlisted(client, db_session):
    seed_cv_inputs(client, db_session)
    body = client.post(BASE, json={"job_evaluation_id": seed_evaluation(db_session).id}).json()
    url = f"{BASE}/{body['id']}/events"
    before = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    assert client.post(url, json={"status": "APPLIED", "occurred_at": before}).status_code == 422
    assert client.post(url, json={"status": "INTERVIEW", "occurred_at": before}).status_code == 422


def test_no_parsed_interview_steps_means_no_planned_rounds(client, db_session):
    seed_cv_inputs(client, db_session)
    evaluation = seed_evaluation(db_session)
    body = client.post(BASE, json={"job_evaluation_id": evaluation.id}).json()
    assert body["planned_events"] == []


def test_application_shows_the_newest_score_and_whether_it_is_outdated(client, db_session):
    seed_cv_inputs(client, db_session)
    old = CandidateProfile(content="old", work_history_id="earlier history")
    evaluation = seed_evaluation(db_session, profile=old)
    app_id = client.post(BASE, json={"job_evaluation_id": evaluation.id}).json()["id"]

    score = client.get(f"{BASE}/{app_id}").json()["evaluation"]
    assert score["id"] == evaluation.id and score["outdated"] is True

    # Re-scored against a profile built from the current work history.
    current = CandidateProfile(content="new", work_history_id=work_history_id(_work_history_payload(db_session)))
    rescored = JobEvaluation(
        job_parse_result_id=evaluation.job_parse_result_id, candidate_profile=current, match_probability=0.2
    )
    db_session.add(rescored)
    db_session.commit()

    (listed,) = client.get(BASE).json()["items"]
    detail = client.get(f"{BASE}/{app_id}").json()
    for body in (listed, detail):
        assert body["evaluation"]["id"] == rescored.id
        assert body["evaluation"]["outdated"] is False
        assert body["evaluation"]["relevance"] < 0


def test_salary_and_work_mode_parsed_and_overridden(client, db_session):
    app_id = _new_application(client, db_session)
    parsed = db_session.get(Application, app_id).job_parse_result
    parsed.salary = {"min": 15000.0, "max": 20000.0, "currency": "PLN", "period": "month", "gross": True, "raw": "15-20k"}
    parsed.work_mode = "hybrid"
    db_session.commit()

    body = client.get(f"{BASE}/{app_id}").json()
    assert body["parsed_salary"]["min"] == 15000.0
    assert body["parsed_salary"]["raw"] == "15-20k"
    assert body["parsed_work_mode"] == "hybrid"
    assert body["salary_override"] is None
    assert body["work_mode_override"] is None

    override = {"min": 18000, "max": 22000, "currency": " eur ", "period": "month", "gross": False}
    body = client.patch(f"{BASE}/{app_id}", json={"salary_override": override, "work_mode_override": "remote"}).json()
    assert body["salary_override"] == {
        "min": 18000.0,
        "max": 22000.0,
        "currency": "EUR",
        "period": "month",
        "gross": False,
        "raw": None,
    }
    assert body["work_mode_override"] == "remote"
    # The parsed values stay underneath.
    assert body["parsed_salary"]["min"] == 15000.0
    assert body["parsed_work_mode"] == "hybrid"

    # Other updates leave the overrides alone; null clears them.
    assert client.patch(f"{BASE}/{app_id}", json={"notes": "x"}).json()["work_mode_override"] == "remote"
    body = client.patch(f"{BASE}/{app_id}", json={"salary_override": None, "work_mode_override": None}).json()
    assert body["salary_override"] is None
    assert body["work_mode_override"] is None

    # An all-empty salary clears the override too.
    body = client.patch(f"{BASE}/{app_id}", json={"salary_override": {"currency": " "}}).json()
    assert body["salary_override"] is None


def test_salary_and_work_mode_override_validation(client, db_session):
    app_id = _new_application(client, db_session)
    assert client.patch(f"{BASE}/{app_id}", json={"salary_override": {"min": 5, "max": 1}}).status_code == 422
    assert client.patch(f"{BASE}/{app_id}", json={"salary_override": {"min": -1}}).status_code == 422
    assert client.patch(f"{BASE}/{app_id}", json={"salary_override": {"period": "decade"}}).status_code == 422
    assert client.patch(f"{BASE}/{app_id}", json={"work_mode_override": "moon"}).status_code == 422
