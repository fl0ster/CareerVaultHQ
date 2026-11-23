import importlib

import httpx
import pytest

from app.tasks.scrape import description, generic

# The package re-exports the ``scrape`` function under the module's name.
scrape_task = importlib.import_module("app.tasks.scrape.scrape")

UNKNOWN_PAGE = """
<html><head>
  <title>Senior Python Developer | Acme Careers</title>
  <meta property="og:site_name" content="Acme">
</head><body>
  <nav>Home Jobs About</nav>
  <main>
    <h1>Senior Python Developer</h1>
    <p>We are looking for a Python developer to build our platform. You will design APIs,
    work with PostgreSQL and Redis, and mentor other engineers on the team.</p>
    <ul><li>5+ years of Python</li><li>FastAPI or Django</li></ul>
  </main>
  <footer>Copyright Acme</footer>
  <script>var tracking = 1;</script>
</body></html>
"""

JSONLD_PAGE = """
<html><head><script type="application/ld+json">
{"@type": "JobPosting", "title": "Data Engineer", "hiringOrganization": {"name": "Globex"},
 "description": "<p>Build pipelines in Spark and Airflow.</p>"}
</script></head><body><h1>Ignored heading</h1></body></html>
"""


def test_generic_parser_reads_main_content():
    assert generic.parse_title(UNKNOWN_PAGE) == "Senior Python Developer"
    assert generic.parse_company(UNKNOWN_PAGE) == "Acme"
    text = generic.parse_description(UNKNOWN_PAGE)
    assert "build our platform" in text
    assert "- 5+ years of Python" in text
    assert "Copyright" not in text
    assert "tracking" not in text


def test_generic_parser_prefers_jsonld():
    assert generic.parse_title(JSONLD_PAGE) == "Data Engineer"
    assert generic.parse_company(JSONLD_PAGE) == "Globex"
    assert "Spark and Airflow" in generic.parse_description(JSONLD_PAGE)


def test_generic_title_falls_back_to_document_title():
    assert generic.parse_title("<html><head><title>QA Engineer - Initech</title></head></html>") == "QA Engineer"


def test_import_job_uses_generic_parser_for_unknown_domains():
    job = description.import_job("https://careers.acme.example/jobs/1", lambda url: UNKNOWN_PAGE)
    assert job.source is None
    assert job.title == "Senior Python Developer"
    assert job.company == "Acme"
    assert "PostgreSQL" in job.description


def test_import_job_uses_the_matching_source(monkeypatch):
    from app.tasks.scrape.sources import skillshot

    monkeypatch.setattr(skillshot, "parse_title", lambda html: "From skillshot")
    monkeypatch.setattr(skillshot, "parse_company", lambda html: "")
    monkeypatch.setattr(skillshot, "parse_description", lambda html: "x" * 200)
    job = description.import_job("https://www.skillshot.pl/offers/1", lambda url: UNKNOWN_PAGE)
    assert job.source == skillshot.NAME
    assert job.title == "From skillshot"
    assert job.company == "Acme"  # empty from the source -> generic fallback
    assert job.description == "x" * 200


def test_import_endpoint_returns_fields_without_storing(client, fake_queue, monkeypatch):
    monkeypatch.setattr(scrape_task, "fetch_html", lambda url: UNKNOWN_PAGE)
    res = client.post("/api/jobs/manual/import", json={"link": "https://careers.acme.example/jobs/1"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["title"] == "Senior Python Developer"
    assert body["source"] is None
    assert fake_queue.jobs == []
    assert client.get("/api/jobs").json()["total"] == 0


@pytest.mark.parametrize("link", ["ftp://x.io/1", "not a url", "javascript:alert(1)"])
def test_import_endpoint_rejects_non_http_links(client, link):
    assert client.post("/api/jobs/manual/import", json={"link": link}).status_code == 422


def test_import_endpoint_reports_fetch_failures(client, monkeypatch):
    def boom(url):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(scrape_task, "fetch_html", boom)
    res = client.post("/api/jobs/manual/import", json={"link": "https://x.io/1"})
    assert res.status_code == 502
