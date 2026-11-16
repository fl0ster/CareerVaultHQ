"""``/api/sources``: listing (synced with the modules on disk) and editing sources."""

from datetime import UTC, datetime

from app import models
from app.services import sources as service
from app.tasks.scrape.sources import SourceInfo
from tests.conftest import ensure_source

BASE = "/api/sources"


def test_list_syncs_modules_and_reports_health_and_relevance(client, db_session):
    body = client.get(BASE).json()

    (skillshot,) = [s for s in body if s["key"] == "skillshot"]
    assert skillshot["name"] == "Skillshot"
    assert skillshot["url"].startswith("https://www.skillshot.pl")
    assert skillshot["enabled"] is True
    assert skillshot["priority"] == 0
    assert skillshot["module_error"] is None
    assert skillshot["health"] == "unknown"
    assert skillshot["last_run_at"] is None
    assert skillshot["relevance"] == {
        "job_count": 0,
        "evaluated_count": 0,
        "avg_match": None,
        "good_match_share": None,
    }


def test_list_orders_by_priority_and_includes_broken_and_job_counts(
    client, db_session, monkeypatch
):
    monkeypatch.setattr(
        service,
        "discover_sources",
        lambda: [
            SourceInfo("alpha", "Alpha", "https://alpha.example"),
            SourceInfo("bad", "bad", None, error="missing NAME"),
        ],
    )
    alpha = ensure_source(db_session, "alpha", priority=3)
    alpha.last_run_at = datetime(2026, 11, 16, tzinfo=UTC)
    alpha.last_scraped_count = 5
    alpha.last_new_count = 2
    db_session.add(models.Job(link="https://alpha.example/1", source=alpha))
    db_session.commit()

    body = client.get(BASE).json()

    assert [s["key"] for s in body] == ["alpha", "bad"]
    assert body[0]["health"] == "healthy"
    assert body[0]["relevance"]["job_count"] == 1
    assert body[0]["last_scraped_count"] == 5
    assert body[1]["health"] == "broken"
    assert body[1]["module_error"] == "missing NAME"


def test_patch_updates_enabled_and_priority(client, db_session):
    client.get(BASE)  # creates the skillshot row

    body = client.patch(f"{BASE}/skillshot", json={"enabled": False}).json()
    assert body["enabled"] is False
    assert body["priority"] == 0

    body = client.patch(f"{BASE}/skillshot", json={"priority": 5}).json()
    assert body["enabled"] is False  # untouched
    assert body["priority"] == 5

    row = service.get_source(db_session, "skillshot")
    db_session.refresh(row)
    assert (row.enabled, row.priority) == (False, 5)


def test_patch_unknown_source_is_404(client):
    assert client.patch(f"{BASE}/nope", json={"enabled": True}).status_code == 404


def test_patch_rejects_bad_payload(client):
    client.get(BASE)
    assert client.patch(f"{BASE}/skillshot", json={"priority": "high"}).status_code == 422
