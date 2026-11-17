from datetime import UTC, datetime

from app import models
from app.services.companies import resolve_company
from tests.conftest import ensure_source


def seed(db_session) -> dict[str, int]:
    src = ensure_source(db_session)
    techland = resolve_company(db_session, "Techland", source=src).company
    resolve_company(db_session, "Techlnad")  # fuzzy alias of Techland
    acme = resolve_company(db_session, "ACME").company
    db_session.flush()
    for i in range(3):
        job = models.Job(link=f"https://example.com/jobs/{i}", source=src)
        db_session.add(
            models.JobParseResult(
                job=job,
                title=f"Job {i}",
                company=techland,
                parsed_at=datetime(2026, 11, 1 + i, tzinfo=UTC),
            )
        )
    job = models.Job(link="https://example.com/jobs/none", source=src)
    db_session.add(models.JobParseResult(job=job, title="No company"))
    db_session.commit()
    return {"techland": techland.id, "acme": acme.id}


def test_list_companies_alphabetically_with_job_counts(client, db_session):
    ids = seed(db_session)

    body = client.get("/api/companies").json()

    assert body["total"] == 2
    assert body["has_more"] is False
    assert [c["name"] for c in body["items"]] == ["ACME", "Techland"]
    assert [c["job_count"] for c in body["items"]] == [0, 3]
    assert body["items"][1]["id"] == ids["techland"]
    assert body["items"][1]["normalized_name"] == "techland"
    assert "aliases" not in body["items"][1]


def test_list_companies_paginates(client, db_session):
    seed(db_session)

    first = client.get("/api/companies", params={"limit": 1}).json()
    assert first["has_more"] is True
    assert first["items"][0]["name"] == "ACME"

    second = client.get("/api/companies", params={"limit": 1, "offset": 1}).json()
    assert second["has_more"] is False
    assert second["items"][0]["name"] == "Techland"


def test_list_companies_search_matches_name_and_aliases(client, db_session):
    seed(db_session)

    by_name = client.get("/api/companies", params={"q": "TECH"}).json()
    assert [c["name"] for c in by_name["items"]] == ["Techland"]
    assert by_name["total"] == 1

    by_alias = client.get("/api/companies", params={"q": "techlnad"}).json()
    assert [c["name"] for c in by_alias["items"]] == ["Techland"]

    assert client.get("/api/companies", params={"q": "nope"}).json()["total"] == 0


def test_list_companies_empty_and_validation(client):
    assert client.get("/api/companies").json() == {
        "items": [], "total": 0, "offset": 0, "limit": 50, "has_more": False,
    }  # fmt: skip
    assert client.get("/api/companies", params={"limit": 0}).status_code == 422
    assert client.get("/api/companies", params={"limit": 999}).status_code == 422


def test_get_company_includes_aliases(client, db_session):
    ids = seed(db_session)

    body = client.get(f"/api/companies/{ids['techland']}").json()

    assert body["name"] == "Techland"
    assert body["job_count"] == 3
    aliases = {a["alias"]: a for a in body["aliases"]}
    assert set(aliases) == {"Techland", "Techlnad"}
    assert aliases["Techland"]["match_kind"] == "new"
    assert aliases["Techland"]["source"] == "skillshot"
    assert aliases["Techlnad"]["match_kind"] == "fuzzy"
    assert aliases["Techlnad"]["similarity"] >= 0.85


def test_get_company_lists_latest_jobs_first(client, db_session):
    ids = seed(db_session)

    body = client.get(f"/api/companies/{ids['techland']}").json()

    assert [j["title"] for j in body["jobs"]] == ["Job 2", "Job 1", "Job 0"]
    newest = body["jobs"][0]
    assert newest["link"] == "https://example.com/jobs/2"
    assert newest["source"] == "skillshot"
    assert newest["parsed_at"].startswith("2026-11-03")
    assert {"job_id", "parse_result_id"} <= set(newest)

    limited = client.get(f"/api/companies/{ids['techland']}", params={"jobs_limit": 2}).json()
    assert [j["title"] for j in limited["jobs"]] == ["Job 2", "Job 1"]
    assert limited["job_count"] == 3

    assert client.get(f"/api/companies/{ids['acme']}").json()["jobs"] == []
    assert (
        client.get(f"/api/companies/{ids['acme']}", params={"jobs_limit": 999}).status_code == 422
    )


def test_get_unknown_company_is_404(client):
    assert client.get("/api/companies/999").status_code == 404


def test_update_company_notes(client, db_session):
    ids = seed(db_session)

    res = client.patch(f"/api/companies/{ids['techland']}", json={"notes": "Great culture"})
    assert res.status_code == 200
    assert res.json()["notes"] == "Great culture"
    assert res.json()["job_count"] == 3

    assert client.get(f"/api/companies/{ids['techland']}").json()["notes"] == "Great culture"
    listed = {c["name"]: c["notes"] for c in client.get("/api/companies").json()["items"]}
    assert listed == {"ACME": "", "Techland": "Great culture"}

    assert client.patch("/api/companies/9999", json={"notes": "x"}).status_code == 404
    assert client.patch(f"/api/companies/{ids['acme']}", json={}).status_code == 422


def test_update_company_tag(client, db_session):
    ids = seed(db_session)
    url = f"/api/companies/{ids['techland']}"

    assert client.get("/api/companies/tags").json() == ["favourite", "interested", "avoid"]
    assert client.get(url).json()["tag"] is None

    client.patch(url, json={"notes": "keep me"})
    res = client.patch(url, json={"tag": "favourite"})
    assert res.status_code == 200
    assert res.json()["tag"] == "favourite"
    assert res.json()["notes"] == "keep me"  # untouched when not sent

    listed = {c["name"]: c["tag"] for c in client.get("/api/companies").json()["items"]}
    assert listed == {"ACME": None, "Techland": "favourite"}

    assert client.patch(url, json={"tag": None}).json()["tag"] is None
    assert client.patch(url, json={"tag": "bogus"}).status_code == 422
    assert client.patch(url, json={"notes": None}).status_code == 422
