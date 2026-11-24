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
        "kind", "date_start", "date_end", "employer", "role", "location", "tech", "context",
    ]  # fmt: skip
    assert items[0]["kind"] == "job"
    assert items[0]["date_start"] == "Jan 2024"
    assert items[0]["date_end"] is None
    assert items[0]["employer"] == "Acme Corp"
    assert items[0]["tech"] == "Python, FastAPI"
    assert items[0]["context"] == ENTRY["context"]


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
    assert exported == _import_payload(kind="job")  # an import without ``kind`` is a job

    # Export output can be imported again unchanged (appends).
    res = client.post(f"{BASE}/json", json=exported)
    assert res.status_code == 201
    assert len(client.get(BASE).json()) == 2


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

    assert client.get(f"{BASE}/companies").json() == {
        str(acme.id): {"current": True, "roles": ["Lead", "Backend Developer"]},
        str(new["company_id"]): {"current": False, "roles": ["Backend Developer"]},
    }


def test_pending_positions_are_not_career_companies(client, db_session):
    from app.services.companies import resolve_company

    resolve_company(db_session, "Acme Corp")
    db_session.commit()
    client.post(BASE, json={**ENTRY, "date_start": "2999-01-01", "date_end": None})
    assert client.get(f"{BASE}/companies").json() == {}
