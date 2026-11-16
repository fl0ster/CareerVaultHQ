from app.models import (
    CandidateProfile,
    Company,
    Job,
    JobEvaluation,
    JobParseResult,
    OpenRouterCall,
    ScrapeRun,
)
from app.services.companies import normalize_company_name
from tests.conftest import ensure_source


def seed(db_session, n: int) -> ScrapeRun:
    run = ScrapeRun(status="finished", new_count=n, scraped_count=n)
    db_session.add(run)
    skillshot, other = ensure_source(db_session, "skillshot"), ensure_source(db_session, "other")
    for i in range(n):
        db_session.add(
            Job(
                link=f"https://example.com/jobs/{i}",
                source=skillshot if i % 2 == 0 else other,
                html="<html></html>" if i % 3 == 0 else None,
                scrape_run=run,
            )
        )
    db_session.commit()
    return run


def _call() -> OpenRouterCall:
    return OpenRouterCall(source="tests", kind=OpenRouterCall.KIND_DECISION, model="m", input={})


def seed_evaluated(db_session, n: int) -> tuple[CandidateProfile, CandidateProfile]:
    """``n`` jobs, all parsed, scored against an old and a new profile. Job ``i`` scores
    ``i / n`` against the new profile and ``0.5`` against the old one. The last job is
    parsed but not evaluated against the new profile."""
    seed(db_session, n)
    old = CandidateProfile(content="old")
    new = CandidateProfile(content="new")
    db_session.add_all([old, new])
    db_session.flush()
    jobs = db_session.query(Job).order_by(Job.id).all()
    for i, job in enumerate(jobs):
        name = f"Company {i}"
        company = Company(name=name, normalized_name=normalize_company_name(name))
        parsed = JobParseResult(
            job=job, title=f"Title {i}", company=company, description=f"Desc {i}"
        )
        db_session.add(parsed)
        db_session.flush()
        db_session.add(
            JobEvaluation(
                job_parse_result_id=parsed.id,
                candidate_profile_id=old.id,
                match_probability=0.5,
                openrouter_call=_call(),
            )
        )
        if i < n - 1:
            db_session.add(
                JobEvaluation(
                    job_parse_result_id=parsed.id,
                    candidate_profile_id=new.id,
                    match_probability=i / n,
                    openrouter_call=_call(),
                )
            )
    db_session.commit()
    return old, new


# --- evaluated jobs -------------------------------------------------------------------


def test_list_jobs_uses_latest_profile_and_includes_parsed_details(client, db_session):
    _, new = seed_evaluated(db_session, 5)

    body = client.get("/api/jobs").json()
    assert body["candidate_profile_id"] == new.id
    assert body["total"] == 4  # the last job is only scored against the old profile
    first = body["items"][0]
    assert first["title"] == "Title 3"
    assert first["company"] == "Company 3"
    assert first["link"] == "https://example.com/jobs/3"
    assert first["has_html"] is True
    assert first["evaluation"]["match_probability"] == 3 / 5
    assert first["evaluation"]["candidate_profile_id"] == new.id
    assert "description" not in first
    assert "html" not in first
    assert all(item["evaluation"]["candidate_profile_id"] == new.id for item in body["items"])


def test_list_jobs_sort_filter_and_pagination(client, db_session):
    seed_evaluated(db_session, 5)

    by_match = client.get("/api/jobs", params={"sort": "match", "limit": 2}).json()
    assert [i["id"] for i in by_match["items"]] == [4, 3]
    assert by_match["has_more"] is True
    last = client.get("/api/jobs", params={"sort": "match", "limit": 2, "offset": 2}).json()
    assert [i["id"] for i in last["items"]] == [2, 1]
    assert last["has_more"] is False

    strong = client.get("/api/jobs", params={"min_probability": 0.4}).json()
    assert strong["total"] == 2  # scores 0.4 and 0.6
    assert all(i["evaluation"]["match_probability"] >= 0.4 for i in strong["items"])

    other = client.get("/api/jobs", params={"source": "other"}).json()
    assert other["total"] == 2
    assert all(i["source"] == "other" for i in other["items"])

    assert client.get("/api/jobs", params={"sort": "bogus"}).status_code == 422
    assert client.get("/api/jobs", params={"min_probability": 2}).status_code == 422


def test_list_jobs_without_profile_is_empty(client, db_session):
    seed(db_session, 3)
    assert client.get("/api/jobs").json() == {
        "items": [], "total": 0, "offset": 0, "limit": 50, "has_more": False,
        "candidate_profile_id": None,
    }  # fmt: skip


def test_get_job_returns_description_and_latest_evaluation(client, db_session):
    _, new = seed_evaluated(db_session, 3)

    body = client.get("/api/jobs/2").json()
    assert body["description"] == "Desc 1"
    assert body["evaluation"]["candidate_profile_id"] == new.id
    assert body["evaluation"]["match_probability"] == 1 / 3
    assert body["evaluation"]["model"] == "m"
    assert body["company"] == "Company 1"

    unscored = client.get("/api/jobs/3").json()  # parsed, only scored against the old profile
    assert unscored["description"] == "Desc 2"
    assert unscored["evaluation"] is None

    assert client.get("/api/jobs/999").status_code == 404


def test_get_job_unparsed_is_404(client, db_session):
    seed(db_session, 1)
    assert client.get("/api/jobs/1").status_code == 404


# --- raw scraped jobs -----------------------------------------------------------------


def test_list_raw_jobs_paginates_newest_first(client, db_session):
    run = seed(db_session, 7)

    first = client.get("/api/jobs/raw", params={"limit": 3}).json()
    assert first["total"] == 7
    assert first["has_more"] is True
    assert first["items"][0]["scrape_run_id"] == run.id
    assert first["items"][0]["has_html"] is True  # Job 6
    assert "html" not in first["items"][0]

    last = client.get("/api/jobs/raw", params={"limit": 3, "offset": 6}).json()
    assert last["has_more"] is False


def test_list_raw_jobs_filter_by_source(client, db_session):
    seed(db_session, 4)
    body = client.get("/api/jobs/raw", params={"source": "other"}).json()
    assert body["total"] == 2
    assert all(j["source"] == "other" for j in body["items"])


def test_list_raw_jobs_empty_and_validation(client):
    assert client.get("/api/jobs/raw").json() == {
        "items": [], "total": 0, "offset": 0, "limit": 50, "has_more": False,
    }  # fmt: skip
    assert client.get("/api/jobs/raw", params={"limit": 0}).status_code == 422
    assert client.get("/api/jobs/raw", params={"limit": 999}).status_code == 422


def test_get_raw_job_includes_html(client, db_session):
    seed(db_session, 1)
    assert client.get("/api/jobs/raw/1").json()["html"] == "<html></html>"
    assert client.get("/api/jobs/raw/999").status_code == 404
