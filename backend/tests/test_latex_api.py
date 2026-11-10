from pathlib import Path

from rq.job import Job
from rq.results import Result

MINIMAL_TEX = b"\\documentclass{article}\\begin{document}Hello\\end{document}\n"


def test_compile_with_upload_enqueues_job(client, fake_queue, upload_root, jobs_root):
    response = client.post(
        "/api/latex/compile", files={"file": ("cv.tex", MINIMAL_TEX, "text/plain")}
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "queued"
    assert body["status_url"].endswith(f"/api/latex/jobs/{body['job_id']}")
    assert body["events_url"].endswith(f"/api/latex/jobs/{body['job_id']}/events")
    assert body["pdf_url"].endswith(f"/api/latex/jobs/{body['job_id']}/pdf")

    assert fake_queue.count == 1
    job = Job.fetch(body["job_id"], connection=fake_queue.connection)
    assert job.func_name == "app.tasks.latex.compile_latex"
    source = (upload_root / body["source"]).resolve()
    assert Path(job.args[0]) == source
    assert Path(job.kwargs["out_dir"]) == (jobs_root / source.parent.name).resolve()
    assert job.meta["source"] == body["source"]


def test_job_status_and_pdf_lifecycle(client, fake_queue, jobs_root):
    job_id = client.post(
        "/api/latex/compile", files={"file": ("cv.tex", MINIMAL_TEX, "text/plain")}
    ).json()["job_id"]

    queued = client.get(f"/api/latex/jobs/{job_id}")
    assert queued.status_code == 200
    assert queued.json()["status"] == "queued"
    assert queued.json()["pdf_url"] is None
    assert client.get(f"/api/latex/jobs/{job_id}/pdf").status_code == 409

    # Simulate the worker finishing the job.
    job = Job.fetch(job_id, connection=fake_queue.connection)
    pdf = (jobs_root / job.meta["source"]).with_suffix(".pdf")
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4 fake")
    Result.create(job, Result.Type.SUCCESSFUL, ttl=60, return_value={"pdf": str(pdf)})
    job.set_status("finished")

    finished = client.get(f"/api/latex/jobs/{job_id}")
    assert finished.json()["status"] == "finished"
    assert finished.json()["pdf_url"].endswith(f"/jobs/{job_id}/pdf")

    download = client.get(f"/api/latex/jobs/{job_id}/pdf")
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/pdf"
    assert download.content == b"%PDF-1.4 fake"


def test_job_status_reports_failure(client, fake_queue):
    job_id = client.post(
        "/api/latex/compile", files={"file": ("cv.tex", MINIMAL_TEX, "text/plain")}
    ).json()["job_id"]
    job = Job.fetch(job_id, connection=fake_queue.connection)
    Result.create_failure(
        job, ttl=60, exc_string="LatexCompileError: pass 1/2 failed\n! Undefined control sequence."
    )
    job.set_status("failed")

    body = client.get(f"/api/latex/jobs/{job_id}").json()
    assert body["status"] == "failed"
    assert "Undefined control sequence" in body["error"]
    assert client.get(f"/api/latex/jobs/{job_id}/pdf").status_code == 409


def test_unknown_job_is_404(client):
    assert client.get("/api/latex/jobs/doesnotexist").status_code == 404
    assert client.get("/api/latex/jobs/doesnotexist/pdf").status_code == 404
    assert client.get("/api/latex/jobs/doesnotexist/events").status_code == 404


def test_events_stream_closes_on_terminal_status(client, fake_queue):
    job_id = client.post(
        "/api/latex/compile", files={"file": ("cv.tex", MINIMAL_TEX, "text/plain")}
    ).json()["job_id"]
    job = Job.fetch(job_id, connection=fake_queue.connection)
    job.set_status("failed")

    with client.stream("GET", f"/api/latex/jobs/{job_id}/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
    assert "event: status" in body
    assert '"status":"failed"' in body
