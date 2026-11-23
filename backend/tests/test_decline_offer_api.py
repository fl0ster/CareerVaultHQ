"""Declining an offer: ``POST /api/applications/{id}/decline``."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models import WorkHistoryEntry
from tests.test_applications_api import BASE, _new_application


def _offer(client, db_session):
    return _new_application(client, db_session, "APPLIED", "INTERVIEW", "OFFER")


def test_declining_an_offer_records_a_final_state(client, db_session):
    app_id = _offer(client, db_session)
    entries = db_session.query(WorkHistoryEntry).count()
    res = client.post(f"{BASE}/{app_id}/decline", json={"note": "Salary too low"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"]["key"] == "DECLINED"
    assert [e["status"]["key"] for e in body["events"]][-2:] == ["OFFER", "DECLINED"]
    assert body["events"][-1]["note"] == "Salary too low"
    # Nothing is added to the work history.
    assert body["work_history_id"] is None
    assert db_session.query(WorkHistoryEntry).count() == entries

    # The application leaves the offers.
    assert client.get(BASE, params={"status": "OFFER"}).json()["total"] == 0
    assert client.get("/api/nav/counts").json()["offers"] == 0
    # Final: nothing can follow it, and the offer cannot be answered again.
    assert client.post(f"{BASE}/{app_id}/events", json={"status": "INTERVIEW"}).status_code == 409
    assert client.post(f"{BASE}/{app_id}/accept", json={"start_date": "2030-01-01"}).status_code == 409
    assert client.post(f"{BASE}/{app_id}/decline", json={}).status_code == 409


def test_decline_note_is_optional(client, db_session):
    app_id = _offer(client, db_session)
    body = client.post(f"{BASE}/{app_id}/decline", json={}).json()
    assert body["status"]["key"] == "DECLINED" and body["events"][-1]["note"] == ""


def test_declining_an_offer_dated_ahead_still_makes_it_current(client, db_session):
    app_id = _new_application(client, db_session, "APPLIED")
    ahead = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    assert client.post(f"{BASE}/{app_id}/events", json={"status": "OFFER", "occurred_at": ahead}).status_code == 201
    assert client.post(f"{BASE}/{app_id}/decline", json={}).json()["status"]["key"] == "DECLINED"


@pytest.mark.parametrize("states", [("APPLIED",), ("APPLIED", "INTERVIEW"), ("REJECTED",), ("CLOSED",)])
def test_only_offers_can_be_declined(client, db_session, states):
    app_id = _new_application(client, db_session, *states)
    assert client.post(f"{BASE}/{app_id}/decline", json={}).status_code == 409


def test_accepted_offers_cannot_be_declined(client, db_session):
    app_id = _offer(client, db_session)
    assert client.post(f"{BASE}/{app_id}/accept", json={"start_date": "2030-01-01"}).status_code == 200
    assert client.post(f"{BASE}/{app_id}/decline", json={}).status_code == 409


def test_declined_is_not_a_plain_state_change(client, db_session):
    app_id = _offer(client, db_session)
    assert client.post(f"{BASE}/{app_id}/events", json={"status": "DECLINED"}).status_code == 422
    offer_id = client.get(f"{BASE}/{app_id}").json()["events"][-1]["id"]
    assert client.patch(f"{BASE}/{app_id}/events/{offer_id}", json={"status": "DECLINED"}).status_code == 422

    declined_id = client.post(f"{BASE}/{app_id}/decline", json={}).json()["events"][-1]["id"]
    assert client.patch(f"{BASE}/{app_id}/events/{declined_id}", json={"status": "OFFER"}).status_code == 422
    # Its note can still be edited.
    body = client.patch(f"{BASE}/{app_id}/events/{declined_id}", json={"note": "Relocation"}).json()
    assert body["events"][-1]["note"] == "Relocation"


def test_removing_declined_reopens_the_offer(client, db_session):
    app_id = _offer(client, db_session)
    declined_id = client.post(f"{BASE}/{app_id}/decline", json={}).json()["events"][-1]["id"]
    body = client.delete(f"{BASE}/{app_id}/events/{declined_id}").json()
    assert body["status"]["key"] == "OFFER"
    # It can be accepted after all.
    assert client.post(f"{BASE}/{app_id}/accept", json={"start_date": "2030-01-01"}).status_code == 200


def test_company_stats_count_declined_offers(client, db_session):
    app_id = _offer(client, db_session)
    company_id = str(client.get(f"{BASE}/{app_id}").json()["job"]["company_id"])
    assert client.get("/api/companies/application-stats").json()[company_id] == {"OFFER": 1}
    client.post(f"{BASE}/{app_id}/decline", json={})
    assert client.get("/api/companies/application-stats").json()[company_id] == {"DECLINED": 1}
