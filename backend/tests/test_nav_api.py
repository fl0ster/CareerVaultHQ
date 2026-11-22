from tests.test_applications_api import BASE, seed_cv_inputs, seed_evaluation
from tests.test_jobs_api import seed_evaluated

URL = "/api/nav/counts"


def test_counts_are_zero_on_an_empty_database(client):
    assert client.get(URL).json() == {"jobs_inbox": 0, "applications": 0, "interviews": 0, "offers": 0}


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
