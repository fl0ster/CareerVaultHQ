"""Technology extraction (``extract_technologies``) and key normalization / matching."""

import json

import httpx
import pytest

from app.config import Settings
from app.services.openrouter import OpenRouterService
from app.services.technologies import match_technologies, technology_key
from app.tasks.parse.parse import extract_technologies

TEXT = (
    "We are looking for a Backend Developer. Requirements: Python 3.11, Django, "
    "PostgreSQL (Postgres 15), Docker, k8s. Nice to have: React.js, AWS. "
    "Experience with Google products is a plus. Agile/Scrum."
)


@pytest.fixture
def chat(db_session):
    state = {"reply": {"technologies": []}, "calls": 0}

    def handle(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        reply = state["reply"]
        content = reply if isinstance(reply, str) else json.dumps(reply)
        return httpx.Response(
            200,
            json={
                "id": "c",
                "model": "m",
                "choices": [{"message": {"role": "assistant", "content": content}}],
                "usage": {"cost": 0.001},
            },
        )

    settings = Settings(openrouter_api_key="sk-test", cors_origins=[])
    state["service"] = OpenRouterService(db_session, settings, transport=httpx.MockTransport(handle))
    return state


def _t(name, evidence):
    return {"name": name, "evidence": evidence}


def test_grounded_technologies_are_kept_and_deduplicated(chat):
    chat["reply"] = {
        "technologies": [
            _t("Python", "Python 3.11"),
            _t("Django", "Django,"),
            _t("PostgreSQL", "PostgreSQL"),
            _t("Postgres", "Postgres 15"),  # same key -> dropped
            _t("Docker", "Docker"),
            _t("Kubernetes", "k8s"),  # alias in evidence
            _t("React", "React.js"),
            _t("AWS", "AWS"),
        ]
    }
    result = extract_technologies(chat["service"], TEXT)
    assert [t["key"] for t in result] == [
        "python",
        "django",
        "postgresql",
        "docker",
        "kubernetes",
        "react",
        "aws",
    ]
    assert result[0] == {"name": "Python", "key": "python"}


def test_hallucinated_technologies_are_dropped(chat):
    chat["reply"] = {
        "technologies": [
            _t("JavaScript", "React.js"),  # inferred, not named in evidence
            _t("Redis", "Redis"),  # evidence not in text
            _t("Go", "Google products"),  # not a whole word
            _t("Flask", "Django"),  # evidence names another technology
            {"name": "Docker"},  # no evidence
            "Docker",
        ]
    }
    assert extract_technologies(chat["service"], TEXT) == []


def test_fenced_and_broken_replies(chat):
    chat["reply"] = '```json\n{"technologies": [{"name": "AWS", "evidence": "AWS"}]}\n```'
    assert extract_technologies(chat["service"], TEXT) == [{"name": "AWS", "key": "aws"}]
    chat["reply"] = "not json"
    assert extract_technologies(chat["service"], TEXT) == []


def test_empty_text_skips_the_call(chat):
    assert extract_technologies(chat["service"], "  ") == []
    assert extract_technologies(chat["service"], None) == []
    assert chat["calls"] == 0


@pytest.mark.parametrize(
    ("spelling", "key"),
    [
        ("ReactJS", "react"),
        ("React.js", "react"),
        ("react-js", "react"),
        ("Postgres", "postgresql"),
        ("Java 17", "java"),
        ("Python 3.11", "python"),
        ("K8s", "kubernetes"),
        ("Golang", "go"),
        ("S3", "s3"),
        ("EC2", "ec2"),
        ("C#", "c#"),
        (" Node JS ", "node.js"),
    ],
)
def test_technology_key(spelling, key):
    assert technology_key(spelling) == key


def test_match_technologies_against_work_history():
    job = [
        {"name": "React", "key": "react"},
        {"name": "PostgreSQL", "key": "postgresql"},
        {"name": "Rust", "key": "rust"},
    ]
    match = match_technologies(job, [["ReactJS", "Python"], ["Postgres"]])
    assert match.matched == ["React", "PostgreSQL"]
    assert match.missing == ["Rust"]
    assert match.ratio == pytest.approx(2 / 3)
    assert match_technologies(None, []).ratio is None
