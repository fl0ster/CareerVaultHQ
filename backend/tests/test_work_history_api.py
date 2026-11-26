BASE = "/api/work-history"

ENTRY = {
    "date_start": "2021-03-01",
    "date_end": "2023-06-30",
    "employer": "Acme Corp",
    "role": "Backend Developer",
    "location": "Warsaw, PL",
    "tech": ["Python", " FastAPI ", "python", ""],
    "context": "Built the billing platform.\n\nLong multi-paragraph description " * 50,
}


def test_create_and_get(client):
    res = client.post(BASE, json=ENTRY)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["employer"] == "Acme Corp"
    assert body["tech"] == ["Python", "FastAPI"]  # trimmed, deduplicated, empties dropped
    assert body["context"] == ENTRY["context"]
    assert body["created_at"] and body["updated_at"]

    got = client.get(f"{BASE}/{body['id']}").json()
    assert got == body


def test_list_orders_by_date_start_desc(client):
    client.post(BASE, json={**ENTRY, "date_start": "2015-01-01", "date_end": "2016-01-01"})
    client.post(BASE, json={**ENTRY, "date_start": "2024-01-01", "date_end": None})
    client.post(BASE, json={**ENTRY, "date_start": "2019-01-01", "date_end": "2020-01-01"})

    items = client.get(BASE).json()
    assert [i["date_start"] for i in items] == ["2024-01-01", "2019-01-01", "2015-01-01"]
    assert items[0]["date_end"] is None


def test_update_partial(client):
    entry_id = client.post(BASE, json=ENTRY).json()["id"]

    res = client.patch(f"{BASE}/{entry_id}", json={"role": "Senior Backend Developer"})
    assert res.status_code == 200
    body = res.json()
    assert body["role"] == "Senior Backend Developer"
    assert body["employer"] == "Acme Corp"  # untouched
    assert body["tech"] == ["Python", "FastAPI"]

    # Explicit null clears date_end (position becomes current).
    body = client.patch(f"{BASE}/{entry_id}", json={"date_end": None}).json()
    assert body["date_end"] is None

    body = client.patch(f"{BASE}/{entry_id}", json={"tech": ["Go", "Go", "Rust"]}).json()
    assert body["tech"] == ["Go", "Rust"]


def test_delete(client):
    entry_id = client.post(BASE, json=ENTRY).json()["id"]
    assert client.delete(f"{BASE}/{entry_id}").status_code == 204
    assert client.get(f"{BASE}/{entry_id}").status_code == 404
    assert client.delete(f"{BASE}/{entry_id}").status_code == 404
    assert client.get(BASE).json() == []


def test_validation(client):
    assert client.get(f"{BASE}/999").status_code == 404
    assert client.patch(f"{BASE}/999", json={"role": "x"}).status_code == 404

    # end before start
    bad = {**ENTRY, "date_start": "2023-01-01", "date_end": "2022-01-01"}
    assert client.post(BASE, json=bad).status_code == 422

    # required fields
    assert client.post(BASE, json={**ENTRY, "employer": ""}).status_code == 422
    missing_role = {k: v for k, v in ENTRY.items() if k != "role"}
    assert client.post(BASE, json=missing_role).status_code == 422

    # update that makes dates inconsistent
    entry_id = client.post(BASE, json=ENTRY).json()["id"]
    res = client.patch(f"{BASE}/{entry_id}", json={"date_end": "2020-01-01"})
    assert res.status_code == 422


def test_json_shape(client):
    assert client.get(f"{BASE}/json").json() == []
    client.post(BASE, json={**ENTRY, "date_start": "2015-01-01", "date_end": "2016-01-01"})
    client.post(BASE, json={**ENTRY, "date_start": "2024-01-01", "date_end": None})

    items = client.get(f"{BASE}/json").json()
    assert isinstance(items, list) and len(items) == 2
    assert list(items[0].keys()) == [
        "kind", "date_start", "date_end", "employer", "role", "location", "tech", "context", "transition",
    ]  # fmt: skip
    assert items[0]["kind"] == "job"
    assert items[0]["date_start"] == "Jan 2024"
    assert items[0]["date_end"] is None
    assert items[0]["employer"] == "Acme Corp"
    assert items[0]["tech"] == "Python, FastAPI"
    assert items[0]["context"] == ENTRY["context"]
    assert items[0]["transition"] is None


# --- JSON import ----------------------------------------------------------------------


def _import_payload(**overrides):
    item = {
        "date_start": "Jan 2020",
        "date_end": "Mar 2022",
        "employer": "Acme",
        "role": "Dev",
        "location": "Remote",
        "tech": "python, sql",
        "context": "did things",
    }
    item.update(overrides)
    return [item]


def test_import_json_round_trips_export(client):
    res = client.post(f"{BASE}/json", json=_import_payload())
    assert res.status_code == 201, res.text
    created = res.json()
    assert len(created) == 1
    assert created[0]["date_start"] == "2020-01-01"
    assert created[0]["date_end"] == "2022-03-01"
    assert created[0]["tech"] == ["python", "sql"]

    exported = client.get(f"{BASE}/json").json()
    # An import without ``kind`` is a job, without ``transition`` a new employment.
    assert exported == _import_payload(kind="job", transition=None)

    # Export output can be imported again unchanged; merging skips the entry already there.
    res = client.post(f"{BASE}/json", json=exported)
    assert res.status_code == 201
    assert res.json() == []
    assert len(client.get(BASE).json()) == 1


def test_import_json_merge_skips_duplicates(client):
    client.post(f"{BASE}/json", json=_import_payload())
    # Same entry with different casing, a new one, and the new one repeated in the payload.
    payload = (
        _import_payload(employer=" ACME ", role="dev")
        + _import_payload(employer="Globex")
        + _import_payload(employer="Globex")
    )
    res = client.post(f"{BASE}/json", json=payload)
    assert res.status_code == 201
    assert [e["employer"] for e in res.json()] == ["Globex"]
    assert sorted(e["employer"] for e in client.get(BASE).json()) == ["Acme", "Globex"]


def test_import_json_replace(client):
    client.post(f"{BASE}/json", json=_import_payload(employer="Old"))
    res = client.post(f"{BASE}/json?replace=true", json=_import_payload(employer="New"))
    assert res.status_code == 201
    entries = client.get(BASE).json()
    assert [e["employer"] for e in entries] == ["New"]


def test_import_json_accepts_list_tech_and_current_position(client):
    res = client.post(f"{BASE}/json", json=_import_payload(date_end=None, tech=["Go", " go ", ""]))
    assert res.status_code == 201
    assert res.json()[0]["date_end"] is None
    assert res.json()[0]["tech"] == ["Go"]


def test_import_json_rejects_bad_date_without_writing(client):
    payload = _import_payload() + _import_payload(date_start="sometime")
    res = client.post(f"{BASE}/json", json=payload)
    assert res.status_code == 422
    assert "entry 1" in res.json()["detail"]
    assert client.get(BASE).json() == []


def test_import_json_rejects_empty(client):
    assert client.post(f"{BASE}/json", json=[]).status_code == 422


# --- education and certificates -------------------------------------------------------

EDUCATION = {
    "kind": "education",
    "date_start": "2012-10-01",
    "date_end": "2015-06-01",
    "employer": "Warsaw University of Technology",
    "role": "B.Sc. Computer Science",
    "context": "Thesis: distributed caches",
}
CERTIFICATE = {"kind": "certificate", "date_start": "2021-03-01", "date_end": None, "role": "AWS Solutions Architect"}


def test_entries_default_to_job(client):
    assert client.post(BASE, json=ENTRY).json()["kind"] == "job"


def test_create_education_and_certificates(client):
    education = client.post(BASE, json=EDUCATION)
    assert education.status_code == 201, education.text
    assert education.json()["kind"] == "education"

    # a certificate without an end date is a single point in time; the issuer may be blank
    point = client.post(BASE, json=CERTIFICATE)
    assert point.status_code == 201, point.text
    assert point.json()["employer"] == "" and point.json()["date_end"] is None

    course = client.post(BASE, json={**CERTIFICATE, "employer": "Coursera", "date_end": "2021-06-01"})
    assert course.status_code == 201

    kinds = [e["kind"] for e in client.get(BASE).json()]
    assert sorted(kinds) == ["certificate", "certificate", "education"]


def test_employer_is_required_for_jobs_only(client):
    assert client.post(BASE, json={**ENTRY, "employer": "  "}).status_code == 422
    assert client.post(BASE, json={**EDUCATION, "employer": ""}).status_code == 201
    assert client.post(BASE, json={**ENTRY, "kind": "hobby"}).status_code == 422


def test_update_switches_kind(client):
    entry_id = client.post(BASE, json=CERTIFICATE).json()["id"]
    # a certificate without an issuer cannot become a job without an employer
    assert client.patch(f"{BASE}/{entry_id}", json={"kind": "job"}).status_code == 422

    body = client.patch(f"{BASE}/{entry_id}", json={"kind": "job", "employer": "Amazon"}).json()
    assert body["kind"] == "job" and body["employer"] == "Amazon"
    body = client.patch(f"{BASE}/{entry_id}", json={"kind": None}).json()  # null keeps the kind
    assert body["kind"] == "job"


def test_a_position_cannot_change_its_kind(client):
    entry_id = client.post(BASE, json=ENTRY).json()["id"]
    for kind in ("education", "certificate"):
        res = client.patch(f"{BASE}/{entry_id}", json={"kind": kind})
        assert res.status_code == 422
        assert "cannot be changed" in res.json()["detail"]
    assert client.get(f"{BASE}/{entry_id}").json()["kind"] == "job"
    assert client.patch(f"{BASE}/{entry_id}", json={"kind": "job", "role": "Lead"}).status_code == 200


def test_import_export_round_trips_kinds(client):
    payload = [
        {**_import_payload()[0], "kind": "job"},
        {"kind": "education", "date_start": "Oct 2012", "date_end": "Jun 2015", "employer": "Uni", "role": "B.Sc."},
        {"kind": "certificate", "date_start": "Mar 2021", "date_end": None, "employer": "", "role": "CKA"},
    ]
    assert client.post(f"{BASE}/json", json=payload).status_code == 201
    exported = client.get(f"{BASE}/json").json()
    assert [(e["kind"], e["role"]) for e in exported] == [("certificate", "CKA"), ("job", "Dev"), ("education", "B.Sc.")]
    assert client.post(f"{BASE}/json?replace=true", json=exported).status_code == 201
    assert client.get(f"{BASE}/json").json() == exported


def test_positions_are_matched_to_known_companies(client, db_session):
    from app.services.companies import resolve_company

    acme = resolve_company(db_session, "Acme Corp").company
    acme.tag = "favourite"
    db_session.commit()

    job = client.post(BASE, json=ENTRY).json()
    assert (job["company_id"], job["company_tag"]) == (acme.id, "favourite")
    # An employer seen only in the career becomes a company, so it can be tagged too.
    new = client.post(
        BASE, json={**ENTRY, "employer": "Nowhere Ltd", "date_start": "2010-01-01", "date_end": "2011-01-01"}
    ).json()
    assert new["company_id"] not in (None, acme.id)
    assert new["company_tag"] is None
    school = client.post(BASE, json={**ENTRY, "kind": "education", "employer": "MIT", "role": "MSc"}).json()
    assert school["company_id"] is None  # only positions are companies
    current = client.post(BASE, json={**ENTRY, "role": "Lead", "date_start": "2023-07-01", "date_end": None}).json()

    listed = {i["id"]: i for i in client.get(BASE).json()}
    assert listed[job["id"]]["company_id"] == acme.id
    assert listed[new["id"]]["company_id"] == new["company_id"]  # resolved again, not duplicated
    assert client.get(f"{BASE}/{current['id']}").json()["company_id"] == acme.id

    companies = client.get("/api/companies").json()
    assert sorted(c["name"] for c in companies["items"]) == ["Acme Corp", "Nowhere Ltd"]

    # Tagging the new company shows on its position.
    client.patch(f"/api/companies/{new['company_id']}", json={"tag": "avoid"})
    assert client.get(f"{BASE}/{new['id']}").json()["company_tag"] == "avoid"

    # Positions are counted in the company stats, next to the application outcomes.
    stats = client.get("/api/companies/application-stats").json()
    assert stats[str(acme.id)] == {"CAREER": 2}
    assert stats[str(new["company_id"])] == {"CAREER": 1}


def test_career_stats_follow_the_work_history(client, db_session):
    from app.services.companies import resolve_company

    # A company known from a job page, without any career entry yet.
    google = resolve_company(db_session, "Google").company
    db_session.commit()
    assert str(google.id) not in client.get("/api/companies/application-stats").json()

    entry = client.post(BASE, json={**ENTRY, "employer": "Google"}).json()
    assert client.get("/api/companies/application-stats").json()[str(google.id)] == {"CAREER": 1}

    client.delete(f"{BASE}/{entry['id']}")
    assert str(google.id) not in client.get("/api/companies/application-stats").json()


def test_application_stats_ghosted_bucket():
    from app.api.routes.companies import _outcome

    assert _outcome({"APPLIED", "GHOSTED"}) == "GHOSTED"
    assert _outcome({"GHOSTED", "REJECTED"}) == "REJECTED"


# --- promotions / role changes ---------------------------------------------------------

JOB = {"employer": "Acme Corp", "role": "Engineer", "location": "Warsaw", "tech": ["Python"]}


def test_promotion_links_and_closes_the_previous_role(client):
    first = client.post(BASE, json={**JOB, "date_start": "2019-01-01", "date_end": None}).json()
    assert first["transition"] is None and first["previous_role_id"] is None

    res = client.post(
        BASE,
        json={**JOB, "employer": "ACME corp.", "role": "Senior Engineer", "date_start": "2022-03-01",
              "transition": "promotion"},
    )  # fmt: skip
    assert res.status_code == 201, res.text
    promoted = res.json()
    assert promoted["transition"] == "promotion"
    assert promoted["previous_role_id"] == first["id"]

    # The ongoing role it continues ends the day before.
    closed = client.get(f"{BASE}/{first['id']}").json()
    assert closed["date_end"] == "2022-02-28"
    listed = {e["id"]: e for e in client.get(BASE).json()}
    assert listed[promoted["id"]]["previous_role_id"] == first["id"]


def test_transition_without_an_earlier_role_stands_alone(client):
    client.post(BASE, json={**JOB, "employer": "Other", "date_start": "2018-01-01", "date_end": "2018-12-31"})
    later = client.post(BASE, json={**JOB, "date_start": "2019-01-01", "transition": "role_change"}).json()
    assert later["transition"] == "role_change"
    assert later["previous_role_id"] is None


def test_transition_does_not_close_an_ended_role(client):
    first = client.post(BASE, json={**JOB, "date_start": "2019-01-01", "date_end": "2021-12-31"}).json()
    client.post(BASE, json={**JOB, "date_start": "2022-06-01", "transition": "promotion"})
    assert client.get(f"{BASE}/{first['id']}").json()["date_end"] == "2021-12-31"


def test_transition_is_for_positions_only(client):
    body = client.post(
        BASE, json={**JOB, "kind": "education", "role": "MSc", "date_start": "2019-01-01", "transition": "promotion"}
    ).json()
    assert body["transition"] is None

    body = client.patch(f"{BASE}/{body['id']}", json={"transition": "promotion"}).json()
    assert body["transition"] is None

    assert client.post(BASE, json={**JOB, "date_start": "2019-01-01", "transition": "demotion"}).status_code == 422


def test_patch_sets_and_clears_the_transition(client):
    first = client.post(BASE, json={**JOB, "date_start": "2019-01-01", "date_end": None}).json()
    second = client.post(BASE, json={**JOB, "role": "Lead", "date_start": "2023-01-01", "date_end": None}).json()
    assert client.get(f"{BASE}/{first['id']}").json()["date_end"] is None  # no transition: left alone

    body = client.patch(f"{BASE}/{second['id']}", json={"transition": "promotion"}).json()
    assert body["previous_role_id"] == first["id"]
    assert client.get(f"{BASE}/{first['id']}").json()["date_end"] == "2022-12-31"

    body = client.patch(f"{BASE}/{second['id']}", json={"transition": None}).json()
    assert body["transition"] is None and body["previous_role_id"] is None


def test_transition_round_trips_through_json(client):
    payload = [
        {"date_start": "Mar 2022", "date_end": None, "employer": "Acme", "role": "Senior Dev", "transition": "promotion"},
        {"date_start": "Jan 2019", "date_end": "Feb 2022", "employer": "Acme", "role": "Dev", "transition": ""},
    ]
    res = client.post(f"{BASE}/json", json=payload)
    assert res.status_code == 201, res.text
    senior, dev = res.json()
    assert senior["previous_role_id"] == dev["id"]
    assert dev["transition"] is None  # "" means a new employment

    exported = client.get(f"{BASE}/json").json()
    assert [e["transition"] for e in exported] == ["promotion", None]

    res = client.post(f"{BASE}/json?replace=true", json=exported)
    assert res.status_code == 201
    senior, dev = res.json()
    assert senior["transition"] == "promotion" and senior["previous_role_id"] == dev["id"]


def test_import_rejects_an_unknown_transition(client):
    res = client.post(f"{BASE}/json", json=_import_payload(transition="sideways"))
    assert res.status_code == 422
