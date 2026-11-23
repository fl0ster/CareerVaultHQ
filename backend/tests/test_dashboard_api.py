from datetime import UTC, datetime, timedelta

from tests.test_applications_api import BASE, seed_cv_inputs, seed_evaluation
from tests.test_jobs_api import seed_evaluated

URL = "/api/dashboard/stats"


def funnel(stats):
    return {stage["key"]: stage["count"] for stage in stats["funnel"]}


def test_empty_database(client):
    stats = client.get(URL).json()
    assert set(funnel(stats).values()) == {0}
    assert [s["key"] for s in stats["funnel"]] == [
        "SCORED",
        "RELEVANT",
        "SHORTLISTED",
        "APPLIED",
        "INTERVIEW",
        "OFFER",
        "ACCEPTED",
    ]
    assert (stats["jobs_inbox"], stats["active"], stats["applied"], stats["responded"]) == (0, 0, 0, 0)
    assert len(stats["weekly_applied"]) == 8
    assert all(w["count"] == 0 for w in stats["weekly_applied"])
    assert stats["upcoming"] == []


def test_scored_jobs_use_the_newest_evaluation(client, db_session):
    seed_evaluated(db_session, 10)  # nine scored, three at or above the 0.6 threshold
    stats = client.get(URL).json()
    assert (funnel(stats)["SCORED"], funnel(stats)["RELEVANT"]) == (9, 3)
    assert stats["jobs_inbox"] == 3


def test_funnel_counts_stages_reached(client, db_session):
    seed_cv_inputs(client, db_session)

    def application(i, *states):
        app_id = client.post(BASE, json={"job_evaluation_id": seed_evaluation(db_session, i).id}).json()["id"]
        for key in states:
            assert client.post(f"{BASE}/{app_id}/events", json={"status": key}).status_code == 201
        return app_id

    application(0)
    application(1, "APPLIED")
    application(2, "APPLIED", "REJECTED")
    application(3, "APPLIED", "INTERVIEW")
    offer = application(4, "APPLIED", "INTERVIEW", "OFFER")
    assert client.post(f"{BASE}/{offer}/accept", json={"start_date": "2027-01-01"}).status_code == 200

    stats = client.get(URL).json()
    assert funnel(stats) == {
        "SCORED": 5,
        "RELEVANT": 5,
        "SHORTLISTED": 5,
        "APPLIED": 4,
        "INTERVIEW": 2,
        "OFFER": 1,
        "ACCEPTED": 1,
    }
    # Shortlisted, applied and interviewing are still open.
    assert (stats["active"], stats["interviews"], stats["offers"]) == (3, 1, 0)
    assert (stats["applied"], stats["responded"]) == (4, 3)
    assert stats["weekly_applied"][-1]["count"] == 4


def test_upcoming_lists_scheduled_rounds(client, db_session):
    seed_cv_inputs(client, db_session)
    app_id = client.post(BASE, json={"job_evaluation_id": seed_evaluation(db_session, 0).id}).json()["id"]
    client.post(f"{BASE}/{app_id}/events", json={"status": "APPLIED"})
    client.post(f"{BASE}/{app_id}/events", json={"status": "INTERVIEW"})
    client.patch(f"{BASE}/{app_id}", json={"interview_rounds": 3})  # rounds 2 and 3 planned
    planned = client.get(f"{BASE}/{app_id}").json()["planned_events"]
    soon = datetime.now(UTC) + timedelta(days=2)
    client.patch(
        f"{BASE}/{app_id}/events/{planned[1]['id']}",
        json={"occurred_at": soon.isoformat(), "title": "Technical"},
    )

    upcoming = client.get(URL).json()["upcoming"]
    assert len(upcoming) == 1  # the unscheduled round is left out
    assert upcoming[0] | {"scheduled_at": None} == {
        "application_id": app_id,
        "job_title": "Title 0",
        "company": "Acme 0",
        "title": "Technical",
        "round": 3,
        "scheduled_at": None,
    }
