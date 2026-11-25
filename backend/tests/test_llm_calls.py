import json
import re
import tomllib
from pathlib import Path

import httpx
import pytest

from app import llm_calls
from app.config import Settings
from app.llm_calls import ALL_CALLS, CV_SUMMARY, JOB_EVALUATION, load_model_overrides, resolve_model
from app.services.openrouter import OpenRouterService

EXAMPLE = Path(__file__).resolve().parents[1] / "llm_models.example.toml"


def _settings(path: Path) -> Settings:
    return Settings(openrouter_api_key="sk-test", cors_origins=[], openrouter_models_file=path)


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "llm_models.toml"
    path.write_text(text)
    return path


def test_registry_is_complete_and_consistent():
    constants = [v for v in vars(llm_calls).values() if isinstance(v, llm_calls.LlmCall)]
    assert set(constants) == set(ALL_CALLS)
    keys = [call.key for call in ALL_CALLS]
    assert len(keys) == len(set(keys))
    for call in ALL_CALLS:
        assert re.fullmatch(r"[a-z][a-z0-9_]*", call.key)
        assert call.kind in ("chat", "decision")
        assert call.model.strip() and call.purpose.strip() and call.source.strip() and call.used_in.strip()


def test_example_file_lists_every_call():
    commented = re.findall(r"^# ([a-z0-9_]+) = \"([^\"]+)\"$", EXAMPLE.read_text(), flags=re.M)
    assert dict(commented) == {call.key: call.model for call in ALL_CALLS}
    # Uncommented as-is, the example must load cleanly.
    uncommented = re.sub(r"^# ([a-z0-9_]+ = )", r"\1", EXAMPLE.read_text(), flags=re.M)
    assert tomllib.loads(uncommented)["models"]["cv_summary"] == CV_SUMMARY.model


def test_missing_file_means_defaults(tmp_path):
    settings = _settings(tmp_path / "missing.toml")
    assert resolve_model(CV_SUMMARY, settings) == CV_SUMMARY.model


def test_override_file_wins_over_default(tmp_path):
    settings = _settings(_write(tmp_path, '[models]\ncv_summary = " anthropic/claude-sonnet-4 "\n'))
    assert resolve_model(CV_SUMMARY, settings) == "anthropic/claude-sonnet-4"
    assert resolve_model(JOB_EVALUATION, settings) == JOB_EVALUATION.model


def test_override_file_from_environment(tmp_path, monkeypatch):
    path = _write(tmp_path, '[models]\njob_evaluation = "typesafe/jev-2"\n')
    monkeypatch.setenv("OPENROUTER_MODELS_FILE", str(path))
    assert resolve_model(JOB_EVALUATION, Settings(cors_origins=[])) == "typesafe/jev-2"


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ('[models]\ncv_sumary = "x/y"\n', "unknown OpenRouter call key"),
        ("[models]\ncv_summary = 3\n", "must be a non-empty string"),
        ('[models]\ncv_summary = ""\n', "must be a non-empty string"),
        ('models = "x"\n', "must be a table"),
        ("[models\n", "invalid TOML"),
    ],
)
def test_bad_override_file_fails_loudly(tmp_path, text, error):
    path = _write(tmp_path, text)
    with pytest.raises(ValueError, match=error):
        load_model_overrides(path)


def test_service_sends_the_overridden_model(tmp_path, db_session):
    settings = _settings(_write(tmp_path, '[models]\njob_evaluation = "typesafe/jev-2"\n'))
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"model": "typesafe/jev-2", "answers": {"q": {"type": "noul", "noul": 0.5}}})

    service = OpenRouterService(db_session, settings, transport=httpx.MockTransport(handle))
    questions = {"q": {"type": "noul", "instructions": "?"}}
    service.decide(state="x", questions=questions, call=JOB_EVALUATION)
    assert json.loads(seen[0].content)["model"] == "typesafe/jev-2"
