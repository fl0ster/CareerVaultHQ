from datetime import date

from rq.job import Job as RqJob
from rq.results import Result

from app.models import Company, GeneratedCV, Job, JobParseResult, WorkHistoryEntry
from tests.conftest import ensure_source

BASE = "/api/cv"
DETAILS = "/api/candidate-details"


def seed_job(db_session, i=0, *, company=True) -> Job:
    job = Job(link=f"https://example.com/jobs/{i}", source=ensure_source(db_session))
    parsed = JobParseResult(job=job, title=f"Title {i}", description=f"Desc {i}")
    if company:
        parsed.company = Company(name=f"Acme {i}", normalized_name=f"acme {i}")
    db_session.add_all([job, parsed])
    db_session.commit()
    return job


def seed_inputs(client, db_session):
    db_session.add(WorkHistoryEntry(date_start=date(2020, 1, 1), employer="Acme", role="Dev", tech=[]))
    db_session.commit()
    assert client.put(DETAILS, json={"first_name": "Jane", "last_name": "Doe"}).status_code == 200


def _cv_jobs(fake_queue):
    return [j for j in fake_queue.jobs if j.func_name.endswith("generate_cv")]


# --- generate --------------------------------------------------------------------------


def test_generate_requires_parsed_job(client, db_session):
    assert client.post(f"{BASE}/generate", json={"job_id": 999}).status_code == 404
    db_session.add(Job(link="https://example.com/unparsed", source=ensure_source(db_session)))
    db_session.commit()
    assert client.post(f"{BASE}/generate", json={"job_id": 1}).status_code == 404


def test_generate_requires_work_history_and_name(client, db_session):
    job = seed_job(db_session)
    res = client.post(f"{BASE}/generate", json={"job_id": job.id})
    assert res.status_code == 400
    assert "work history" in res.json()["detail"]

    db_session.add(WorkHistoryEntry(date_start=date(2020, 1, 1), employer="Acme", role="Dev", tech=[]))
    db_session.commit()
    res = client.post(f"{BASE}/generate", json={"job_id": job.id})
    assert res.status_code == 400
    assert "first and last name" in res.json()["detail"]

    client.put(DETAILS, json={"first_name": "Jane", "last_name": " "})
    assert client.post(f"{BASE}/generate", json={"job_id": job.id}).status_code == 400


def test_generate_creates_row_and_enqueues_task(client, db_session, fake_queue):
    job = seed_job(db_session)
    seed_inputs(client, db_session)

    res = client.post(f"{BASE}/generate", json={"job_id": job.id})
    assert res.status_code == 202, res.text
    body = res.json()
    assert body["status"] == "queued"
    assert body["job"] == {
        "id": job.id,
        "title": "Title 0",
        "company": "Acme 0",
        "link": "https://example.com/jobs/0",
        "source": "skillshot",
    }
    assert body["pdf_url"] is None
    assert body["warnings"] == []

    jobs = _cv_jobs(fake_queue)
    assert len(jobs) == 1
    assert jobs[0].args == (body["id"],)
    assert jobs[0].meta == {"generated_cv_id": body["id"], "job_id": job.id}
    cv = db_session.get(GeneratedCV, body["id"])
    assert cv.rq_job_id == jobs[0].id

    # A second generation for the same job is a separate row.
    assert client.post(f"{BASE}/generate", json={"job_id": job.id}).json()["id"] != body["id"]


def test_generate_marks_row_failed_when_queue_is_down(client, db_session, fake_queue, monkeypatch):
    job = seed_job(db_session)
    seed_inputs(client, db_session)

    def boom(*args, **kwargs):
        raise ConnectionError("redis down")

    monkeypatch.setattr(fake_queue, "enqueue", boom)
    res = client.post(f"{BASE}/generate", json={"job_id": job.id})
    assert res.status_code == 503
    listed = client.get(BASE).json()
    assert listed["total"] == 1
    assert listed["items"][0]["status"] == "failed"
    assert "could not enqueue" in listed["items"][0]["error"]


# --- list / get -------------------------------------------------------------------------


def test_list_and_filter_by_job(client, db_session):
    first, second = seed_job(db_session, 0), seed_job(db_session, 1, company=False)
    seed_inputs(client, db_session)
    a = client.post(f"{BASE}/generate", json={"job_id": first.id}).json()["id"]
    b = client.post(f"{BASE}/generate", json={"job_id": second.id}).json()["id"]
    c = client.post(f"{BASE}/generate", json={"job_id": first.id}).json()["id"]

    page = client.get(BASE).json()
    assert [i["id"] for i in page["items"]] == [c, b, a]
    assert page["total"] == 3 and page["has_more"] is False
    assert page["items"][1]["job"]["company"] is None

    only_first = client.get(BASE, params={"job_id": first.id}).json()
    assert [i["id"] for i in only_first["items"]] == [c, a]

    paged = client.get(BASE, params={"limit": 2}).json()
    assert paged["has_more"] is True and len(paged["items"]) == 2

    by_company = client.get(BASE, params={"q": "acme"}).json()
    assert [i["id"] for i in by_company["items"]] == [c, a] and by_company["total"] == 2
    by_title = client.get(BASE, params={"q": "TITLE 1"}).json()
    assert [i["id"] for i in by_title["items"]] == [b]
    assert client.get(BASE, params={"q": "100%"}).json()["total"] == 0

    assert client.get(f"{BASE}/{a}").json()["id"] == a
    assert client.get(f"{BASE}/999").status_code == 404


def test_get_reconciles_with_failed_rq_job(client, db_session, fake_queue):
    job = seed_job(db_session)
    seed_inputs(client, db_session)
    cv_id = client.post(f"{BASE}/generate", json={"job_id": job.id}).json()["id"]
    rq_job = RqJob.fetch(_cv_jobs(fake_queue)[0].id, connection=fake_queue.connection)
    Result.create_failure(rq_job, ttl=60, exc_string="JobTimeoutException: killed")
    rq_job.set_status("failed")

    body = client.get(f"{BASE}/{cv_id}").json()
    assert body["status"] == "failed"
    assert "JobTimeoutException" in body["error"]
    assert db_session.get(GeneratedCV, cv_id).status == "failed"


# --- files / delete ---------------------------------------------------------------------


def _finish(db_session, client, cv_id, settings_root):
    cv = db_session.get(GeneratedCV, cv_id)
    folder = settings_root / str(cv_id)
    folder.mkdir(parents=True)
    (folder / "cv.pdf").write_bytes(b"%PDF-1.4 fake")
    (folder / "cv.tex").write_text("\\documentclass{article}")
    cv.status = "finished"
    cv.pdf_path = str(folder / "cv.pdf")
    cv.tex_path = str(folder / "cv.tex")
    cv.headline_role = "Senior Dev"
    cv.core_technologies = ["Python"]
    cv.pipeline = {"warnings": ["summary could not be generated; left empty"], "cost": 0.0123}
    db_session.commit()
    return folder


def test_pdf_and_tex_download_lifecycle(client, db_session, tmp_path):
    from app.config import get_settings
    from app.main import app

    cv_root = app.dependency_overrides[get_settings]().cv_root
    job = seed_job(db_session)
    seed_inputs(client, db_session)
    cv_id = client.post(f"{BASE}/generate", json={"job_id": job.id}).json()["id"]

    assert client.get(f"{BASE}/{cv_id}/pdf").status_code == 409
    assert client.get(f"{BASE}/{cv_id}/tex").status_code == 409

    folder = _finish(db_session, client, cv_id, cv_root)
    body = client.get(f"{BASE}/{cv_id}").json()
    assert body["status"] == "finished"
    assert body["pdf_url"].endswith(f"/api/cv/{cv_id}/pdf")
    assert body["tex_url"].endswith(f"/api/cv/{cv_id}/tex")
    assert body["headline_role"] == "Senior Dev"
    assert body["warnings"] == ["summary could not be generated; left empty"]
    assert body["cost"] == 0.0123

    pdf = client.get(f"{BASE}/{cv_id}/pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert 'filename="Jane_Doe_CV_Acme_0.pdf"' in pdf.headers["content-disposition"]
    assert pdf.content == b"%PDF-1.4 fake"
    tex = client.get(f"{BASE}/{cv_id}/tex")
    assert tex.status_code == 200
    assert 'filename="Jane_Doe_CV_Acme_0.tex"' in tex.headers["content-disposition"]
    assert client.get(f"{BASE}/{cv_id}/pipeline").json()["warnings"] == body["warnings"]

    assert client.delete(f"{BASE}/{cv_id}").status_code == 204
    assert not folder.exists()
    assert client.get(f"{BASE}/{cv_id}").status_code == 404
    assert client.delete(f"{BASE}/{cv_id}").status_code == 404


def test_delete_refuses_while_running(client, db_session):
    job = seed_job(db_session)
    seed_inputs(client, db_session)
    cv_id = client.post(f"{BASE}/generate", json={"job_id": job.id}).json()["id"]
    assert client.delete(f"{BASE}/{cv_id}").status_code == 409


def test_failed_cv_pdf_reports_error(client, db_session):
    job = seed_job(db_session)
    seed_inputs(client, db_session)
    cv_id = client.post(f"{BASE}/generate", json={"job_id": job.id}).json()["id"]
    cv = db_session.get(GeneratedCV, cv_id)
    cv.status, cv.error = "failed", "LatexCompileError: boom"
    db_session.commit()
    res = client.get(f"{BASE}/{cv_id}/pdf")
    assert res.status_code == 409
    assert res.json()["detail"] == "LatexCompileError: boom"
