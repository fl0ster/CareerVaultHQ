"""CV import pipeline: PDF text/link extraction, the LLM call and the validation of its reply."""

import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

import app.tasks.cv_import as cv_import_task
from app.config import Settings
from app.models import OpenRouterCall
from app.schemas.candidate_details import CandidateDetailsIn
from app.services.openrouter import REDACTED, OpenRouterService
from app.tasks.cv_import import import_cv
from app.tasks.cv_import.extract import CvImportError, build_result, extract_cv, extract_pdf
from tests.cv_pdf import make_pdf


def reply(**overrides):
    data = {
        "first_name": "Jane",
        "last_name": "Doe",
        "email": "jane.doe@example.com",
        "phone": "+48 600 700 800",
        "location": "Warsaw, Poland",
        "website": "",
        "github": "https://github.com/janedoe",
        "linkedin": "",
        "summary": "",
        "work_history": [
            {
                "employer": "Globex",
                "role": "Software Developer",
                "location": "",
                "date_start": "2018",
                "date_end": "2021-02",
                "tech": ["Django", "Celery", "Redis", "django"],
                "context": "- Django REST APIs, Celery workers and Redis caching",
            },
            {
                "employer": "Acme Corp",
                "role": "Senior Backend Engineer",
                "location": "",
                "date_start": "2021-03",
                "date_end": "present",
                "tech": ["Python", "FastAPI", "PostgreSQL", "AWS Lambda"],
                "context": "- Built payment services\n- Led the migration to AWS Lambda",
            },
        ],
        "education": [
            {
                "degree": "MSc Computer Science",
                "institution": "Warsaw University of Technology",
                "date_start": "2013",
                "date_end": "2018-06",
                "note": "",
            }
        ],
        "skills": ["Python", "Go", "Kubernetes", "Terraform"],
        "certifications": [
            {"name": "AWS Solutions Architect", "issuer": "Amazon", "date_start": "2022-04", "date_end": ""},
            {"name": "Kubernetes bootcamp", "issuer": "", "date_start": "2019-09", "date_end": "2019-12"},
        ],
        "languages": [{"language": "Polish", "level": "native"}, {"language": "English", "level": "C1"}],
    }
    data.update(overrides)
    return data


@pytest.fixture
def settings():
    return Settings(openrouter_api_key="sk-test", cors_origins=[], cv_import_min_text_chars=50)


@pytest.fixture
def chat(db_session, settings):
    state = {"reply": reply(), "requests": []}

    def handle(request: httpx.Request) -> httpx.Response:
        state["requests"].append(json.loads(request.content))
        content = state["reply"] if isinstance(state["reply"], str) else json.dumps(state["reply"])
        return httpx.Response(
            200,
            json={
                "id": "c",
                "model": "m",
                "choices": [{"message": {"role": "assistant", "content": content}}],
                "usage": {"cost": 0.002},
            },
        )

    state["service"] = OpenRouterService(db_session, settings, transport=httpx.MockTransport(handle))
    return state


@pytest.fixture
def cv_file(tmp_path):
    def write(data: bytes | None = None, name: str = "cv.pdf"):
        path = tmp_path / "upload" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(make_pdf() if data is None else data)
        return path

    return write


def pdf_text(path, **limits):
    return extract_pdf(path, **{"max_pages": 10, "max_chars": 60_000, "min_chars": 50, **limits})


# --------------------------------------------------------------------------- PDF


def test_extract_pdf_reads_text_and_link_annotations(cv_file):
    pdf = pdf_text(cv_file())
    assert "Acme Corp - Senior Backend Engineer" in pdf.text
    assert pdf.links == [
        "https://www.linkedin.com/in/jane-doe/",
        "https://github.com/janedoe",
        "mailto:jane.doe@example.com",
    ]
    assert (pdf.pages, pdf.pages_read, pdf.warnings) == (1, 1, [])


def test_extract_pdf_limits_pages_and_characters(cv_file):
    pdf = pdf_text(cv_file(make_pdf(pages=3)), max_pages=2, max_chars=300)
    assert (pdf.pages, pdf.pages_read, len(pdf.text)) == (3, 2, 300)
    assert pdf.warnings == ["only the first 2 of 3 pages were read", "the CV text was cut to its first 300 characters"]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (make_pdf([]), "no text layer"),
        (make_pdf(password="secret"), "password-protected"),
        (b"%PDF-1.7\nthis is not really a PDF", "could not read the PDF"),
    ],
    ids=["scan", "encrypted", "corrupt"],
)
def test_unusable_pdfs_are_rejected(cv_file, data, message):
    with pytest.raises(CvImportError, match=message):
        pdf_text(cv_file(data))


def test_pdf_with_an_empty_user_password_is_read(cv_file):
    assert "Jane Doe" in pdf_text(cv_file(make_pdf(password=""))).text


# --------------------------------------------------------------------------- LLM + validation


def test_extract_cv_returns_importable_data(chat, cv_file, settings):
    result = extract_cv(chat["service"], pdf_text(cv_file()))

    [request] = chat["requests"]
    assert request["temperature"] == 0
    assert request["response_format"]["type"] == "json_schema"
    assert request["response_format"]["json_schema"]["strict"] is True
    assert "https://www.linkedin.com/in/jane-doe/" in request["messages"][-1]["content"]

    details = result.candidate_details
    assert (details.first_name, details.last_name, details.location) == ("Jane", "Doe", "Warsaw, Poland")
    assert details.email == "jane.doe@example.com"
    assert details.phone == "+48 600 700 800"
    assert details.github == "github.com/janedoe"
    assert details.linkedin == "linkedin.com/in/jane-doe"  # backfilled from the link annotation
    assert [(lang.language, lang.level) for lang in details.languages] == [("Polish", "native"), ("English", "C1")]
    CandidateDetailsIn.model_validate(details.model_dump())

    # positions, education and certificates form one timeline, newest first
    timeline = [(e.kind, e.role, e.employer, e.date_start, e.date_end) for e in result.work_history]
    assert timeline == [
        ("certificate", "AWS Solutions Architect", "Amazon", "Apr 2022", None),  # a single point in time
        ("job", "Senior Backend Engineer", "Acme Corp", "Mar 2021", None),
        ("certificate", "Kubernetes bootcamp", "", "Sep 2019", "Dec 2019"),  # a course with a duration
        ("job", "Software Developer", "Globex", "Jan 2018", "Feb 2021"),
        ("education", "MSc Computer Science", "Warsaw University of Technology", "Jan 2013", "Jun 2018"),
    ]
    _, acme, _, globex, _ = result.work_history
    assert globex.tech == ["Django", "Celery", "Redis"]
    assert acme.context == "- Built payment services\n- Led the migration to AWS Lambda"
    for entry in result.work_history:
        entry.to_create()

    assert result.skills == ["Python", "Go", "Kubernetes", "Terraform"]
    assert result.warnings == [
        "Software Developer at Globex: only the year is stated, so January was assumed",
        "education MSc Computer Science at Warsaw University of Technology: only the year is stated, so January was assumed",
    ]
    assert result.source.characters > 0 and result.source.pages == 1


def test_private_cv_text_is_not_stored(chat, cv_file, settings, db_session):
    extract_cv(chat["service"], pdf_text(cv_file()))
    call = db_session.scalar(select(OpenRouterCall))
    assert call.source == "tasks.cv_import"
    assert call.input["redacted"] is True
    assert all(m["content"] == REDACTED for m in call.input["messages"] if m["role"] != "system")


def test_fenced_or_wrapped_json_is_accepted(chat, cv_file, settings):
    chat["reply"] = "Here you go:\n```json\n" + json.dumps(reply()) + "\n```"
    assert extract_cv(chat["service"], pdf_text(cv_file())).candidate_details.first_name == "Jane"


def test_non_json_reply_fails(chat, cv_file, settings):
    chat["reply"] = "Sorry, I cannot help with that."
    with pytest.raises(CvImportError, match="JSON"):
        extract_cv(chat["service"], pdf_text(cv_file()))


def test_contacts_not_in_the_cv_are_dropped(cv_file):
    pdf = pdf_text(cv_file())
    result = build_result(
        reply(email="jane@invented.example", phone="+1 555 0100", website="https://jane.dev", github=""), pdf
    )
    details = result.candidate_details
    assert details.email == "jane.doe@example.com"  # backfilled from the CV after the invented one was dropped
    assert details.phone == ""
    assert details.website == ""
    assert details.github == "github.com/janedoe"
    assert "email 'jane@invented.example' was not found in the CV and was dropped" in result.warnings
    assert "phone '+1 555 0100' was not found in the CV and was dropped" in result.warnings
    assert "website 'https://jane.dev' was not found in the CV and was dropped" in result.warnings


def test_bad_work_entries_are_skipped_with_warnings(cv_file):
    pdf = pdf_text(cv_file())
    entries = [
        {"employer": "", "role": "Intern", "date_start": "2015", "date_end": "2015"},
        {"employer": "Initech", "role": "Developer", "date_start": "", "date_end": "2016"},
        {"employer": "Hooli", "role": "Engineer", "date_start": "2020-05", "date_end": "2019-01"},
        {"employer": "Umbrella", "role": "Consultant", "date_start": "May 2017", "date_end": ""},
        "not an object",
    ]
    result = build_result(reply(work_history=entries, education=[], certifications=[]), pdf)

    assert [(e.employer, e.date_start, e.date_end) for e in result.work_history] == [
        ("Hooli", "Jan 2019", "May 2020"),
        ("Umbrella", "May 2017", None),
    ]
    assert result.warnings == [
        "skipped Intern: the employer or the role is missing",
        "skipped Developer at Initech: no start date could be read ('')",
        "Engineer at Hooli: the end date was before the start date, so they were swapped",
        "Consultant at Umbrella: no end date is stated, so it is treated as a current position",
    ]


def test_education_and_certificate_dates(cv_file):
    pdf = pdf_text(cv_file())
    education = [
        {"degree": "PhD", "institution": "MIT", "date_start": "2020-10", "date_end": "present", "note": "AI"},
        {"degree": "", "institution": "High School No. 1", "date_start": "", "date_end": "2011", "note": ""},
        {"degree": "BSc", "institution": "Uni", "date_start": "2016-10", "date_end": "", "note": ""},
        {"degree": "Course", "institution": "", "date_start": "", "date_end": "", "note": ""},
        {"degree": "", "institution": "", "date_start": "2010", "date_end": "", "note": ""},
    ]
    certifications = [
        {"name": "CKA", "issuer": "CNCF", "date_start": "", "date_end": "2023-05"},
        {"name": "Scrum Master", "issuer": "", "date_start": "", "date_end": ""},
        "Google Cloud Professional Architect (2021)",
        "Toastmasters",
        {"name": "CKA", "issuer": "CNCF", "date_start": "2023-05", "date_end": ""},
    ]
    result = build_result(reply(work_history=[], education=education, certifications=certifications), pdf)

    timeline = [(e.kind, e.role, e.employer, e.date_start, e.date_end, e.context) for e in result.work_history]
    assert timeline == [
        ("certificate", "CKA", "CNCF", "May 2023", None, None),  # issue date given as the end; duplicate dropped
        ("certificate", "Google Cloud Professional Architect (2021)", "", "Jan 2021", None, None),
        ("education", "PhD", "MIT", "Oct 2020", None, "AI"),  # still studying
        ("education", "BSc", "Uni", "Oct 2016", None, None),
        ("education", "High School No. 1", "", "Jan 2011", "Jan 2011", None),  # only the graduation year
    ]
    assert "skipped certificate Scrum Master: no date could be read, add it by hand" in result.warnings
    assert "skipped certificate Toastmasters: no date could be read, add it by hand" in result.warnings
    assert "skipped education Course: no date could be read, add it by hand" in result.warnings
    assert "education BSc at Uni: no end date is stated, so it is treated as ongoing" in result.warnings
    assert not any("PhD" in warning for warning in result.warnings)


def test_garbage_reply_shapes_do_not_crash(cv_file):
    pdf = pdf_text(cv_file())
    result = build_result(
        {"first_name": 42, "work_history": "none", "education": [None], "certifications": [1, None], "languages": {}},
        pdf,
    )
    assert result.candidate_details.first_name == ""
    assert result.work_history == []
    assert "no work history was found" in result.warnings
    assert "the candidate's name was not found" in result.warnings


# --------------------------------------------------------------------------- RQ job


def test_import_cv_job_returns_json_and_deletes_the_upload(chat, cv_file, settings, monkeypatch, engine):
    monkeypatch.setattr(cv_import_task, "get_settings", lambda: settings)
    monkeypatch.setattr(cv_import_task, "OpenRouterService", lambda session, _settings: chat["service"])
    path = cv_file()

    data = import_cv(str(path))

    assert data["candidate_details"]["first_name"] == "Jane"
    assert [(e["kind"], e["date_start"]) for e in data["work_history"]][:2] == [
        ("certificate", "Apr 2022"),
        ("job", "Mar 2021"),
    ]
    json.dumps(data)
    assert not path.exists()
    assert not path.parent.exists()


def test_import_cv_job_deletes_the_upload_on_failure(chat, cv_file, settings, monkeypatch, engine):
    monkeypatch.setattr(cv_import_task, "get_settings", lambda: settings)
    path = cv_file(make_pdf([]))

    with pytest.raises(CvImportError):
        import_cv(str(path))

    assert chat["requests"] == []
    assert not path.exists()


def test_worker_can_resolve_the_job_function():
    """The worker imports the job by name in a fresh process, before any router is loaded.
    A tasks -> app.api import would close a cycle (the routers import the tasks back) that
    RQ reports only as "Invalid attribute name: import_cv"."""
    code = "from rq.utils import import_attribute; import_attribute('app.tasks.cv_import.import_cv')"
    backend = Path(__file__).resolve().parents[1]
    done = subprocess.run([sys.executable, "-c", code], cwd=backend, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
