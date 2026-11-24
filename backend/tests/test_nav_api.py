from datetime import UTC, datetime, timedelta

from tests.test_applications_api import BASE, seed_cv_inputs, seed_evaluation
from tests.test_jobs_api import seed_evaluated

URL = "/api/nav/counts"


def test_counts_are_zero_on_an_empty_database(client):
    assert client.get(URL).json() == {
        "jobs_inbox": 0,
        "applications": 0,
        "interviews": 0,
        "offers": 0,
        "work_history": 0,
    }


def test_jobs_inbox_count_matches_the_inbox(client, db_session):
    seed_evaluated(db_session, 10)  # three jobs at or above the 0.6 threshold
    inbox = client.get("/api/jobs/inbox").json()
    assert client.get(URL).json()["jobs_inbox"] == inbox["count"] == 3

    client.put(f"/api/jobs/{inbox['items'][0]['id']}/decision", json={"decision": "rejected"})
    assert client.get(URL).json()["jobs_inbox"] == 2


def test_application_counts_follow_the_current_stage(client, db_session):
    seed_cv_inputs(client, db_session)

    def application(i, *states):
        evaluation = seed_evaluation(db_session, i)
        app_id = client.post(BASE, json={"job_evaluation_id": evaluation.id}).json()["id"]
        for key in states:
            assert client.post(f"{BASE}/{app_id}/events", json={"status": key}).status_code == 201
        return app_id

    application(0, "APPLIED")
    interview = application(1, "APPLIED", "INTERVIEW")
    application(2, "APPLIED", "INTERVIEW", "OFFER")

    counts = client.get(URL).json()
    assert (counts["applications"], counts["interviews"], counts["offers"]) == (3, 1, 1)
    # Applications are not inbox jobs.
    assert counts["jobs_inbox"] == 0

    client.post(f"{BASE}/{interview}/events", json={"status": "OFFER"})
    counts = client.get(URL).json()
    assert (counts["interviews"], counts["offers"]) == (0, 2)


def test_stage_counts_use_the_latest_held_event(client, db_session):
    """Planned rounds and back-dated states do not count as the current stage."""
    seed_cv_inputs(client, db_session)
    planned = client.post(BASE, json={"job_evaluation_id": seed_evaluation(db_session, 0).id}).json()["id"]
    client.post(f"{BASE}/{planned}/events", json={"status": "APPLIED"})
    client.post(f"{BASE}/{planned}/events", json={"status": "INTERVIEW"})
    client.patch(f"{BASE}/{planned}", json={"interview_rounds": 4})  # three more planned rounds
    assert client.post(f"{BASE}/{planned}/events", json={"status": "REJECTED"}).status_code == 201

    backdated = client.post(BASE, json={"job_evaluation_id": seed_evaluation(db_session, 1).id}).json()["id"]
    client.post(f"{BASE}/{backdated}/events", json={"status": "INTERVIEW"})
    past = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    client.post(f"{BASE}/{backdated}/events", json={"status": "OFFER", "occurred_at": past})

    counts = client.get(URL).json()
    assert (counts["applications"], counts["interviews"], counts["offers"]) == (2, 1, 0)
    # Same answer as the ORM's notion of the current state.
    keys = [client.get(f"{BASE}/{i}").json()["status"]["key"] for i in (planned, backdated)]
    assert keys == ["REJECTED", "INTERVIEW"]


def test_work_history_count(client):
    entry = {"kind": "job", "date_start": "2020-01-01", "employer": "Acme", "role": "Engineer", "tech": []}
    created = client.post("/api/work-history", json=entry)
    assert created.status_code == 201, created.text
    assert client.get(URL).json()["work_history"] == 1

    client.delete(f"/api/work-history/{created.json()['id']}")
    assert client.get(URL).json()["work_history"] == 0
