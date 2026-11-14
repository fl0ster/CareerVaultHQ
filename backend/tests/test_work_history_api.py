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
        "date_start", "date_end", "employer", "role", "location", "tech", "context",
    ]  # fmt: skip
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
    assert exported == _import_payload()

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
