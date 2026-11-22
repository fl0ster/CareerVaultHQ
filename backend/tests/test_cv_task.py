import importlib
import json
from datetime import date

import httpx
import pytest
from sqlalchemy import select

from app import models
from app.config import Settings
from app.db import init_db, session_factory
from app.services.openrouter import OpenRouterService
from tests.conftest import ensure_source

generate_task = importlib.import_module("app.tasks.cv.generate")

RELEVANCE = {"Zartis": 0.96, "VGW": 0.95, "Old Corp": 0.05}


def _chat_reply(system: str, user: str) -> str:
    """Answer the chat prompts of every pipeline step based on their system prompt."""
    if "Group the technologies" in system:
        return json.dumps(
            [
                {"category": "Mobile", "technologies": ["React Native"]},
                {"category": "Languages", "technologies": ["TypeScript", "Invented"]},
            ]
        )
    if "professional summary" in system:
        return '"Senior mobile engineer with React Native experience."'
    if "core technologies" in system:
        return '["TypeScript", "React Native", "Jest"]'
    if "headline job title" in system:
        return "Senior React Native Engineer"
    if "Rewrite the list of technologies" in system:
        return "TypeScript, React Native"
    if "Condense the context" in system:
        return "Maintained a legacy PHP shop."
    if "Rewrite the context" in system:
        return "Shipped tailored features. Improved performance."
    raise AssertionError(f"unexpected system prompt: {system[:60]}")


def _handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    if request.url.path.endswith("/decisions"):
        employer = body["state"]["past_role"]["employer"]
        return httpx.Response(
            200,
            json={
                "id": "dec",
                "model": "typesafe/jev-1.14",
                "answers": {"is_relevant": {"type": "noul", "noul": RELEVANCE[employer]}},
                "usage": {"input_tokens": 10, "output_tokens": 0, "cost": 0.0001},
            },
        )
    system = next(m["content"] for m in body["messages"] if m["role"] == "system")
    user = next(m["content"] for m in body["messages"] if m["role"] == "user")
    return httpx.Response(
        200,
        json={
            "id": "gen",
            "model": body["model"],
            "choices": [{"message": {"role": "assistant", "content": _chat_reply(system, user)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0002},
        },
    )


@pytest.fixture
def requests_seen():
    return []


@pytest.fixture
def task_engine(engine, monkeypatch, tmp_path, requests_seen):
    """Temporary database, mocked OpenRouter, fake pdflatex, CV root under tmp_path."""
    settings = Settings(
        openrouter_api_key="sk-test",
        cors_origins=[],
        cv_root=tmp_path / "cv",
        cv_max_workers=3,
        # Three fixture roles, one irrelevant: keep it condensed rather than backfilled.
        cv_min_entries=2,
    )
    state = {"handler": _handler}

    def handle(request):
        requests_seen.append(request)
        return state["handler"](request)

    monkeypatch.setattr(generate_task, "init_db", lambda: init_db(engine))
    monkeypatch.setattr(generate_task, "session_factory", lambda: session_factory(engine))
    monkeypatch.setattr(generate_task, "get_settings", lambda: settings)
    monkeypatch.setattr(
        generate_task,
        "OpenRouterService",
        lambda session, *_a, **_k: OpenRouterService(session, settings, transport=httpx.MockTransport(handle)),
    )

    def fake_compile(tex_path, *, out_dir=None, **_kwargs):
        pdf = tmp_path / "cv" / tex_path.split("/")[-2] / "cv.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        return {"pdf": str(pdf), "log": "", "log_tail": "Output written", "passes": 2}

    state["compile"] = fake_compile
    monkeypatch.setattr(generate_task, "compile_latex", lambda *a, **k: state["compile"](*a, **k))
    engine.set_handler = lambda handler: state.__setitem__("handler", handler)
    engine.set_compile = lambda fn: state.__setitem__("compile", fn)
    engine.cv_root = tmp_path / "cv"
    return engine


def _seed(engine, *, details=True, history=True) -> int:
    """A parsed job, three work history rows and the candidate's details; returns the id
    of a queued ``GeneratedCV`` for the job."""
    with session_factory(engine)() as session:
        job = models.Job(link="https://example.com/jobs/1", source=ensure_source(session))
        parsed = models.JobParseResult(
            job=job,
            title="React Native Developer",
            company=models.Company(name="ACME", normalized_name="acme"),
            description="We need React Native and TypeScript.",
        )
        session.add_all([job, parsed])
        if history:
            session.add_all(
                [
                    models.WorkHistoryEntry(
                        date_start=date(2024, 7, 1),
                        employer="VGW",
                        role="Senior Mobile Engineer",
                        tech=["React Native", "TypeScript", "Jest"],
                        context="Built pipelines. Led the app.",
                    ),
                    models.WorkHistoryEntry(
                        date_start=date(2025, 5, 1),
                        date_end=date(2026, 5, 1),
                        employer="Zartis",
                        role="Senior Mobile Engineer",
                        tech=["React Native", "RTK Query"],
                        context="Gym app work.",
                    ),
                    models.WorkHistoryEntry(
                        date_start=date(2012, 1, 1),
                        date_end=date(2013, 12, 1),
                        employer="Old Corp",
                        role="PHP Developer",
                        tech=["PHP"],
                        context="Legacy shop. Nothing relevant, left because of complaints.",
                    ),
                ]
            )
        if details:
            session.add(
                models.CandidateDetails(
                    first_name="Jane",
                    last_name="Doe",
                    email="jane@example.com",
                    languages=[{"language": "English", "level": "C1"}],
                )
            )
        session.flush()
        cv = models.GeneratedCV(job_parse_result_id=parsed.id, rq_job_id="rq-1")
        session.add(cv)
        session.commit()
        return cv.id


def test_generate_cv_runs_the_whole_pipeline(task_engine, requests_seen):
    cv_id = _seed(task_engine)

    result = generate_task.generate_cv(cv_id)

    assert result["status"] == "finished"
    assert result["warnings"] == []
    with session_factory(task_engine)() as session:
        cv = session.get(models.GeneratedCV, cv_id)
        assert cv.status == "finished"
        assert cv.started_at is not None and cv.finished_at is not None
        assert cv.headline_role == "Senior React Native Engineer"
        assert cv.core_technologies == ["TypeScript", "React Native"]  # max 2, only known ones
        assert cv.summary == "Senior mobile engineer with React Native experience."
        assert cv.pdf_path == str(task_engine.cv_root / str(cv_id) / "cv.pdf")
        tex = open(cv.tex_path, encoding="utf-8").read()
        pipeline = cv.pipeline

        # 1. every role scored, the irrelevant one condensed into "Additional Experience".
        assert {r["employer"]: r["relevance"] for r in pipeline["relevance"]} == RELEVANCE
        assert [e["employer"] for e in pipeline["main"]] == ["Zartis", "VGW"]
        assert [e["employer"] for e in pipeline["early"]] == ["Old Corp"]
        assert pipeline["early"][0]["context"] == "Maintained a legacy PHP shop."
        # Zartis (shorter, more relevant) wins the overlap; VGW keeps its larger piece.
        assert pipeline["main"][1]["date_end"] == "Apr 2025"
        assert pipeline["main"][0]["date_end"] == "May 2026"
        assert any(line.startswith("trimmed") for line in pipeline["timeline_log"])

        # 3. contexts and technologies tailored.
        assert all(e["context"] == "Shipped tailored features. Improved performance." for e in pipeline["main"])
        assert all(e["tech"] == "TypeScript, React Native" for e in pipeline["main"])

        # 4. categories keep only the candidate's technologies and drop invented ones.
        assert pipeline["categories"] == [
            ["Mobile", ["React Native"]],
            ["Languages", ["TypeScript"]],
        ]

        # 5. the document.
        assert "\\bfseries Jane Doe\\par" in tex
        assert "{Senior Mobile Engineer}{Zartis}{May 2025 -- May 2026}" in tex
        assert "{Additional Experience}{Various Companies}{Jan 2012 -- Dec 2013}" in tex
        assert "\\cvitem{English}{{\\color{muted}C1}}" in tex
        assert "Nothing relevant" not in tex
        assert (task_engine.cv_root / str(cv_id) / "pipeline.json").is_file()
        # 3 decisions at 0.0001 + 9 chat calls at 0.0002
        assert pipeline["openrouter_calls"] == 12
        assert pipeline["cost"] == pytest.approx(3 * 0.0001 + 9 * 0.0002)

        # Every call was logged under this task's source labels.
        sources = {c.source for c in session.scalars(select(models.OpenRouterCall))}
        assert sources == {
            "tasks.cv.relevance", "tasks.cv.context", "tasks.cv.tech", "tasks.cv.early",
            "tasks.cv.categories", "tasks.cv.summary", "tasks.cv.role", "tasks.cv.core_tech",
        }  # fmt: skip
    # 3 decisions + 2x2 main + 1 early + 4 headline calls
    assert len(requests_seen) == 3 + 4 + 1 + 4


def test_generate_cv_falls_back_and_warns_when_calls_fail(task_engine, requests_seen):
    cv_id = _seed(task_engine)

    def flaky(request):
        body = json.loads(request.content)
        if request.url.path.endswith("/decisions"):
            return _handler(request)
        system = next(m["content"] for m in body["messages"] if m["role"] == "system")
        if "professional summary" in system or "Rewrite the context" in system:
            return httpx.Response(502, json={"error": {"message": "provider down"}})
        return _handler(request)

    task_engine.set_handler(flaky)
    result = generate_task.generate_cv(cv_id)

    assert result["status"] == "finished"
    assert "summary could not be generated; left empty" in result["warnings"]
    assert any(w.startswith("context of Senior Mobile Engineer @ VGW") for w in result["warnings"])
    with session_factory(task_engine)() as session:
        cv = session.get(models.GeneratedCV, cv_id)
        assert cv.summary == ""
        assert cv.pipeline["main"][1]["context"] == "Built pipelines. Led the app."  # original kept
        failed = session.scalars(select(models.OpenRouterCall).where(models.OpenRouterCall.status == "failed")).all()
        assert len(failed) == 2 * (2 + 1)  # two attempts for each of 2 contexts + 1 summary


def test_generate_cv_marks_failure_and_reraises(task_engine):
    cv_id = _seed(task_engine, details=False)

    with pytest.raises(generate_task.CvGenerationError, match="first and last name"):
        generate_task.generate_cv(cv_id)

    with session_factory(task_engine)() as session:
        cv = session.get(models.GeneratedCV, cv_id)
        assert cv.status == "failed"
        assert cv.error.startswith("CvGenerationError: missing candidate details")
        assert cv.finished_at is not None


def test_generate_cv_fails_when_latex_fails(task_engine):
    from app.tasks.latex import LatexCompileError

    cv_id = _seed(task_engine)

    def broken(*_a, **_k):
        raise LatexCompileError("pdflatex pass 1/2 exited with code 1\n! Undefined control sequence.")

    task_engine.set_compile(broken)
    with pytest.raises(LatexCompileError):
        generate_task.generate_cv(cv_id)
    with session_factory(task_engine)() as session:
        cv = session.get(models.GeneratedCV, cv_id)
        assert cv.status == "failed"
        assert "Undefined control sequence" in cv.error
        assert cv.tex_path is None  # nothing recorded for a failed run
        assert (task_engine.cv_root / str(cv_id) / "cv.tex").is_file()  # but kept for debugging


def test_generate_cv_without_work_history(task_engine):
    cv_id = _seed(task_engine, history=False)
    with pytest.raises(generate_task.CvGenerationError, match="missing work history"):
        generate_task.generate_cv(cv_id)


def test_generate_cv_unknown_row(task_engine):
    with pytest.raises(ValueError, match="unknown generated cv"):
        generate_task.generate_cv(999)


def test_generate_cv_is_a_noop_when_already_finished(task_engine, requests_seen):
    cv_id = _seed(task_engine)
    with session_factory(task_engine)() as session:
        cv = session.get(models.GeneratedCV, cv_id)
        cv.status = "finished"
        cv.pdf_path = "/x/cv.pdf"
        session.commit()
    assert generate_task.generate_cv(cv_id)["pdf_path"] == "/x/cv.pdf"
    assert requests_seen == []
