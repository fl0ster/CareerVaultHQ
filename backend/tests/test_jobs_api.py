from datetime import UTC, datetime, timedelta

from app.models import Job, ScrapeRun


def seed(db_session, n: int) -> ScrapeRun:
    run = ScrapeRun(status="finished", new_count=n, scraped_count=n)
    db_session.add(run)
    base = datetime(2026, 11, 1, tzinfo=UTC)
    for i in range(n):
        db_session.add(
            Job(
                title=f"Job {i}",
                link=f"https://example.com/jobs/{i}",
                date_added="2026-11-01",
                source="skillshot" if i % 2 == 0 else "other",
                description="desc" if i % 3 == 0 else None,
                scraped_at=base + timedelta(minutes=i),
                scrape_run=run,
            )
        )
    db_session.commit()
    return run


def test_list_jobs_paginates_newest_first(client, db_session):
    run = seed(db_session, 7)

    first = client.get("/api/jobs", params={"limit": 3}).json()
    assert first["total"] == 7
    assert first["has_more"] is True
    assert [j["title"] for j in first["items"]] == ["Job 6", "Job 5", "Job 4"]
    assert first["items"][0]["scrape_run_id"] == run.id
    assert first["items"][0]["has_description"] is True  # Job 6
    assert "description" not in first["items"][0]

    last = client.get("/api/jobs", params={"limit": 3, "offset": 6}).json()
    assert [j["title"] for j in last["items"]] == ["Job 0"]
    assert last["has_more"] is False


def test_list_jobs_filter_by_source(client, db_session):
    seed(db_session, 4)
    body = client.get("/api/jobs", params={"source": "other"}).json()
    assert body["total"] == 2
    assert all(j["source"] == "other" for j in body["items"])


def test_list_jobs_empty_and_validation(client):
    assert client.get("/api/jobs").json() == {
        "items": [], "total": 0, "offset": 0, "limit": 50, "has_more": False,
    }  # fmt: skip
    assert client.get("/api/jobs", params={"limit": 0}).status_code == 422
    assert client.get("/api/jobs", params={"limit": 999}).status_code == 422


def test_get_job_detail(client, db_session):
    seed(db_session, 1)
    job_id = client.get("/api/jobs").json()["items"][0]["id"]
    body = client.get(f"/api/jobs/{job_id}").json()
    assert body["description"] == "desc"
    assert client.get("/api/jobs/999").status_code == 404
