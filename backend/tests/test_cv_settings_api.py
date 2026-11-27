from app import models

BASE = "/api/cv-settings"

DEFAULTS = {"max_entries": 5, "min_entries": 3, "high_relevance": 0.6, "irrelevant_relevance": 0.25, "min_months": 3}


def test_starts_with_the_defaults_and_the_default_consent(client):
    body = client.get(BASE).json()
    assert body["rules"] == DEFAULTS
    assert body["defaults"] == DEFAULTS
    assert body["overridden"] == []
    assert body["consent_text"].startswith("I consent to the processing of my personal data")


def test_consent_is_seeded_from_the_personal_details(client, db_session):
    db_session.add(models.CandidateDetails(first_name="Jane", consent_text="Legacy clause."))
    db_session.commit()
    assert client.get(BASE).json()["consent_text"] == "Legacy clause."


def test_put_overrides_and_resets_rules(client):
    body = client.put(BASE, json={"consent_text": " Mine. ", "max_entries": 7, "high_relevance": 0.6}).json()
    assert body["consent_text"] == "Mine."
    assert body["rules"] == {**DEFAULTS, "max_entries": 7}
    # a value equal to its default is not an override
    assert body["overridden"] == ["max_entries"]
    assert client.get(BASE).json() == body

    body = client.put(BASE, json={"consent_text": ""}).json()
    assert body["consent_text"] == ""
    assert body["rules"] == DEFAULTS and body["overridden"] == []


def test_put_validates(client):
    assert client.put(BASE, json={"high_relevance": 1.5}).status_code == 422
    assert client.put(BASE, json={"max_entries": 0}).status_code == 422
    assert client.put(BASE, json={"min_entries": 6}).status_code == 422  # > default max of 5
    assert client.put(BASE, json={"irrelevant_relevance": 0.7}).status_code == 422  # > default high
    assert client.put(BASE, json={"min_entries": 6, "max_entries": 8}).status_code == 200


def test_personal_details_no_longer_touch_the_consent(client):
    client.put(BASE, json={"consent_text": "Kept."})
    client.put("/api/candidate-details", json={"first_name": "Jane", "consent_text": "Ignored."})
    assert client.get(BASE).json()["consent_text"] == "Kept."
