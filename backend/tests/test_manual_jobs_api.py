from app.tasks.scrape.sources import manual


def test_add_manual_job_enqueues_parse(client, fake_queue):
    res = client.post(
        "/api/jobs/manual",
        json={"title": " Backend dev ", "company": "Acme", "description": "Python"},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "NOT_STARTED"
    assert len(fake_queue.jobs) == 1

    status = client.get(f"/api/jobs/manual/{body['job_id']}")
    assert status.json()["status"] == "NOT_STARTED"
    assert client.get("/api/jobs/manual/999999").status_code == 404


def test_add_manual_job_validates(client):
    assert client.post("/api/jobs/manual", json={"title": "  "}).status_code == 422
    first = client.post("/api/jobs/manual", json={"title": "A", "link": "https://x.io/1"})
    assert first.status_code == 201
    dup = client.post("/api/jobs/manual", json={"title": "B", "link": "https://x.io/1"})
    assert dup.status_code == 409


def test_manual_source_round_trips_fields():
    html = manual.to_html("T", "C", "D")
    assert manual.parse_title(html) == "T"
    assert manual.parse_company(html) == "C"
    assert manual.parse_description(html) == "D"
    assert manual.parse_title("not json") == ""
