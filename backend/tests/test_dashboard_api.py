from datetime import UTC, date, datetime, timedelta

from tests.test_applications_api import BASE, seed_cv_inputs, seed_evaluation
from tests.test_jobs_api import seed_evaluated

URL = "/api/dashboard/stats"


def links(stats):
    return {(link["source"], link["target"]): link["value"] for link in stats["flow"]["links"]}


def inflow(stats):
    """``{node id: what flows into it}``, the root counting what flows out."""
    totals: dict[str, int] = {}
    for (source, target), value in links(stats).items():
        totals[target] = totals.get(target, 0) + value
        if source == "scored":
            totals["scored"] = totals.get("scored", 0) + value
    return totals


def test_empty_database(client):
    stats = client.get(URL).json()
    assert stats["flow"] == {"nodes": [], "links": []}
    assert (stats["jobs_inbox"], stats["active"], stats["applied"], stats["responded"]) == (0, 0, 0, 0)
    assert len(stats["weekly_applied"]) == 8
    assert all(w["count"] == 0 for w in stats["weekly_applied"])
    assert stats["upcoming"] == []


def test_scored_jobs_use_the_newest_evaluation(client, db_session):
    seed_evaluated(db_session, 10)  # nine scored, three at or above the 0.6 threshold
    stats = client.get(URL).json()
    assert links(stats) == {("scored", "relevant"): 3, ("scored", "scored:drop"): 6, ("relevant", "relevant:waiting"): 3}
    assert stats["jobs_inbox"] == 3
    nodes = {n["id"]: (n["column"], n["kind"]) for n in stats["flow"]["nodes"]}
    assert nodes == {
        "scored": (0, "stage"),
        "relevant": (1, "stage"),
        "relevant:waiting": (2, "pending"),
        "scored:drop": (1, "drop"),
    }


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
    assert links(stats) == {
        ("scored", "relevant"): 5,
        ("relevant", "shortlisted"): 5,
        ("shortlisted", "applied"): 4,
        ("shortlisted", "shortlisted:waiting"): 1,
        ("applied", "interview"): 2,
        ("applied", "applied:waiting"): 1,
        ("applied", "applied:rejected"): 1,
        ("interview", "offer"): 1,
        ("interview", "interview:waiting"): 1,
        ("offer", "offer:accepted"): 1,
    }
    # Every node passes on what reaches it.
    totals = inflow(stats)
    for node in ("relevant", "shortlisted", "applied", "interview"):
        assert sum(v for (s, _), v in links(stats).items() if s == node) == totals[node]
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


def test_flow_splits_every_way_an_application_can_stop(client, db_session):
    seed_cv_inputs(client, db_session)

    def application(i, *states):
        app_id = client.post(BASE, json={"job_evaluation_id": seed_evaluation(db_session, i).id}).json()["id"]
        for key in states:
            assert client.post(f"{BASE}/{app_id}/events", json={"status": key}).status_code == 201
        return app_id

    application(0, "CLOSED")
    application(1, "APPLIED", "CLOSED")
    application(2, "APPLIED", "INTERVIEW", "REJECTED")
    application(3, "APPLIED", "INTERVIEW", "CLOSED")
    declined = application(4, "APPLIED", "INTERVIEW", "OFFER")
    assert client.post(f"{BASE}/{declined}/decline", json={"note": "no"}).status_code == 200

    stats = client.get(URL).json()
    assert links(stats) == {
        ("scored", "relevant"): 5,
        ("relevant", "shortlisted"): 5,
        ("shortlisted", "applied"): 4,
        ("shortlisted", "shortlisted:closed"): 1,
        ("applied", "interview"): 3,
        ("applied", "applied:closed"): 1,
        ("interview", "offer"): 1,
        ("interview", "interview:rejected"): 1,
        ("interview", "interview:closed"): 1,
        ("offer", "offer:declined"): 1,
    }
    assert (stats["applied"], stats["responded"], stats["active"]) == (4, 3, 0)


def test_weekly_applied_buckets_by_first_applied_date(client, db_session):
    seed_cv_inputs(client, db_session)
    now = datetime.now(UTC)
    for i, days_ago in enumerate((0, 7, 7, 14, 70)):  # the last one is outside the 8 weeks
        app = client.post(BASE, json={"job_evaluation_id": seed_evaluation(db_session, i).id}).json()
        app_id = app["id"]
        # Applying cannot be dated before shortlisting, so shortlist well before.
        shortlisted = {"occurred_at": (now - timedelta(days=100)).isoformat()}
        assert client.patch(f"{BASE}/{app_id}/events/{app['events'][0]['id']}", json=shortlisted).status_code == 200
        when = (now - timedelta(days=days_ago)).isoformat()
        assert client.post(f"{BASE}/{app_id}/events", json={"status": "APPLIED", "occurred_at": when}).status_code == 201

    weeks = client.get(URL).json()["weekly_applied"]
    assert [w["count"] for w in weeks] == [0, 0, 0, 0, 0, 1, 2, 1]
    starts = [date.fromisoformat(w["week_start"]) for w in weeks]
    assert all(s.weekday() == 0 for s in starts)
    assert starts[-1] == now.date() - timedelta(days=now.weekday())
