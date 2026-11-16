"""``/api/queue``: current and pending background jobs."""

from rq.executions import Execution

from app.tasks.scrape.scrape import scrape

BASE = "/api/queue"


def test_empty_queue(client):
    assert client.get(BASE).json() == {"current": None, "pending": [], "pending_count": 0}


def test_reports_current_and_pending_in_order(client, fake_queue):
    first = fake_queue.enqueue(scrape, "skillshot", job_id="a" * 32)
    second = fake_queue.enqueue(scrape, None, job_id="b" * 32, description="scrape everything")

    # Simulate the worker having picked up ``first``.
    fake_queue.remove(first)
    first.set_status("started")
    with fake_queue.connection.pipeline() as pipe:
        Execution.create(first, ttl=600, pipeline=pipe)
        pipe.execute()

    body = client.get(BASE).json()
    assert body["current"]["job_id"] == first.id
    assert body["current"]["kind"] == "scrape"
    assert body["current"]["description"] == "scrape('skillshot')"
    assert body["current"]["status"] == "started"
    assert body["pending_count"] == 1
    assert [p["job_id"] for p in body["pending"]] == [second.id]
    assert body["pending"][0]["description"] == "scrape everything"
    assert body["pending"][0]["status"] == "queued"
