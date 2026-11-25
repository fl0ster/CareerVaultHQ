"""Accepting an offer: ``POST /api/applications/{id}/accept`` and the pending work-history
entry it creates."""

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.api.routes.cv import check_cv_inputs
from app.models import Application, WorkHistoryEntry
from app.services.candidate_profile import _work_history_payload
from app.tasks.cv.generate import load_roles
from tests.test_applications_api import BASE, _new_application

START = date.today() + timedelta(days=30)


def _prefill_jobs(fake_queue):
    return [j for j in fake_queue.jobs if j.func_name.endswith("prefill_work_entry")]


def _offer(client, db_session):
    return _new_application(client, db_session, "APPLIED", "INTERVIEW", "OFFER")


def test_accepting_an_offer_adds_a_pending_work_history_entry(client, db_session, fake_queue):
    app_id = _offer(client, db_session)
    res = client.post(f"{BASE}/{app_id}/accept", json={"start_date": START.isoformat()})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"]["key"] == "ACCEPTED"
    assert body["start_date"] == START.isoformat()
    assert [e["status"]["key"] for e in body["events"]][-2:] == ["OFFER", "ACCEPTED"]

    entry = client.get(f"/api/work-history/{body['work_history_id']}").json()
    assert entry["application_id"] == app_id
    assert entry["pending"] is True
    assert entry["prefill_state"] == "queued"
    assert entry["date_start"] == START.isoformat() and entry["date_end"] is None
    assert (entry["employer"], entry["role"]) == ("Acme 0", "Title 0")

    jobs = _prefill_jobs(fake_queue)
    assert len(jobs) == 1 and jobs[0].args == (entry["id"],)

    # The application leaves the offers.
    assert client.get(BASE, params={"status": "OFFER"}).json()["total"] == 0
    assert client.get("/api/nav/counts").json()["offers"] == 0


def test_accepting_an_offer_dated_ahead_still_makes_it_current(client, db_session):
    app_id = _new_application(client, db_session, "APPLIED")
    ahead = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    assert client.post(f"{BASE}/{app_id}/events", json={"status": "OFFER", "occurred_at": ahead}).status_code == 201
    body = client.post(f"{BASE}/{app_id}/accept", json={"start_date": START.isoformat()}).json()
    assert body["status"]["key"] == "ACCEPTED"


def test_accept_uses_the_stored_start_date(client, db_session):
    app_id = _offer(client, db_session)
    res = client.post(f"{BASE}/{app_id}/accept", json={})
    assert res.status_code == 422

    assert client.patch(f"{BASE}/{app_id}", json={"start_date": START.isoformat()}).json()["start_date"] == START.isoformat()
    body = client.post(f"{BASE}/{app_id}/accept", json={}).json()
    assert body["status"]["key"] == "ACCEPTED"
    entry = db_session.get(WorkHistoryEntry, body["work_history_id"])
    assert entry.date_start == START

    assert client.patch(f"{BASE}/{app_id}", json={"start_date": None}).json()["start_date"] is None


@pytest.mark.parametrize("states", [("APPLIED",), ("APPLIED", "INTERVIEW"), ("REJECTED",)])
def test_only_offers_can_be_accepted(client, db_session, states):
    app_id = _new_application(client, db_session, *states)
    res = client.post(f"{BASE}/{app_id}/accept", json={"start_date": START.isoformat()})
    assert res.status_code == 409
    assert db_session.query(WorkHistoryEntry).filter(WorkHistoryEntry.application_id.is_not(None)).count() == 0


def test_an_offer_is_accepted_once(client, db_session):
    app_id = _offer(client, db_session)
    assert client.post(f"{BASE}/{app_id}/accept", json={"start_date": START.isoformat()}).status_code == 200
    assert client.post(f"{BASE}/{app_id}/accept", json={"start_date": START.isoformat()}).status_code == 409


def test_accepted_is_not_a_plain_state_change(client, db_session):
    app_id = _offer(client, db_session)
    assert client.post(f"{BASE}/{app_id}/events", json={"status": "ACCEPTED"}).status_code == 422
    offer_id = client.get(f"{BASE}/{app_id}").json()["events"][-1]["id"]
    assert client.patch(f"{BASE}/{app_id}/events/{offer_id}", json={"status": "ACCEPTED"}).status_code == 422

    body = client.post(f"{BASE}/{app_id}/accept", json={"start_date": START.isoformat()}).json()
    accepted_id = body["events"][-1]["id"]
    assert client.patch(f"{BASE}/{app_id}/events/{accepted_id}", json={"status": "OFFER"}).status_code == 422
    # Final: nothing can follow it.
    assert client.post(f"{BASE}/{app_id}/events", json={"status": "INTERVIEW"}).status_code == 409


def test_removing_accepted_undoes_the_acceptance(client, db_session):
    app_id = _offer(client, db_session)
    body = client.post(f"{BASE}/{app_id}/accept", json={"start_date": START.isoformat()}).json()
    entry_id, accepted_id = body["work_history_id"], body["events"][-1]["id"]

    body = client.delete(f"{BASE}/{app_id}/events/{accepted_id}").json()
    assert body["status"]["key"] == "OFFER" and body["work_history_id"] is None
    assert client.get(f"/api/work-history/{entry_id}").status_code == 404
    # It can be accepted again.
    assert client.post(f"{BASE}/{app_id}/accept", json={"start_date": START.isoformat()}).status_code == 200


def test_deleting_the_application_keeps_the_entry(client, db_session):
    app_id = _offer(client, db_session)
    entry_id = client.post(f"{BASE}/{app_id}/accept", json={"start_date": START.isoformat()}).json()["work_history_id"]
    assert client.delete(f"{BASE}/{app_id}").status_code == 204
    entry = client.get(f"/api/work-history/{entry_id}").json()
    assert entry["application_id"] is None


def test_deleting_the_entry_keeps_the_application_accepted(client, db_session):
    app_id = _offer(client, db_session)
    entry_id = client.post(f"{BASE}/{app_id}/accept", json={"start_date": START.isoformat()}).json()["work_history_id"]
    assert client.delete(f"/api/work-history/{entry_id}").status_code == 204
    body = client.get(f"{BASE}/{app_id}").json()
    assert body["status"]["key"] == "ACCEPTED" and body["work_history_id"] is None
    assert db_session.get(Application, app_id) is not None


def test_pending_entries_stay_out_of_cvs_and_the_profile(client, db_session):
    app_id = _offer(client, db_session)  # also adds a 2020 position
    client.post(f"{BASE}/{app_id}/accept", json={"start_date": START.isoformat()})

    assert [r.employer for r in load_roles(db_session)] == ["Acme"]
    assert [e["employer"] for e in _work_history_payload(db_session)] == ["Acme"]
    # Once it starts it counts.
    assert [r.employer for r in load_roles(db_session, today=START)] == ["Acme 0", "Acme"]


def test_only_pending_positions_do_not_count_as_work_history(db_session):
    db_session.add(WorkHistoryEntry(date_start=START, employer="Next", role="Dev", tech=[]))
    db_session.commit()
    with pytest.raises(HTTPException) as exc:
        check_cv_inputs(db_session)
    assert "work history" in exc.value.detail


def test_pending_flag_follows_the_start_date(client):
    today = date.today()
    for start, pending in ((today + timedelta(days=1), True), (today, False), (today - timedelta(days=1), False)):
        res = client.post("/api/work-history", json={"date_start": start.isoformat(), "employer": "E", "role": "R"})
        body = res.json()
        assert (body["pending"], body["application_id"], body["prefill_state"]) == (pending, None, None)


def test_removing_applied_undoes_an_accepted_offer(client, db_session):
    app_id = _offer(client, db_session)
    body = client.post(f"{BASE}/{app_id}/accept", json={"start_date": START.isoformat()}).json()
    applied = next(e["id"] for e in body["events"] if e["status"]["key"] == "APPLIED")

    body = client.delete(f"{BASE}/{app_id}/events/{applied}").json()
    assert [e["status"]["key"] for e in body["events"]] == ["SHORTLISTED"]
    assert db_session.query(WorkHistoryEntry).filter(WorkHistoryEntry.application_id.is_not(None)).count() == 0
