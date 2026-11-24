import os
import re
import tomllib
from pathlib import Path

import pytest

from app.api.routes import openrouter as openrouter_routes
from app.config import Settings
from app.services import candidate_profile, score_explanation
from app.services.llm.config import (
    KIND_CHAT,
    KIND_DECISION,
    ProviderConfig,
    api_key,
    get_llm_config,
    load_llm_config,
    parse_llm_config,
)
from app.services.llm.errors import LlmConfigError, OpenRouterNotConfigured
from app.services.llm.providers import (
    JevDecisions,
    OpenAICompatibleChat,
    OpenRouterChat,
    build_chat_provider,
    build_decision_provider,
)
from app.tasks.cv import generate as cv_generate
from app.tasks.cv_import import extract as cv_import_extract
from app.tasks.evaluate import evaluate
from app.tasks.gmail import rejections
from app.tasks.parse import parse
from app.tasks.work_history import prefill

SHIPPED = Path(Settings().llm_config_path)

CODE_TASKS = {
    candidate_profile.TASK: KIND_CHAT,
    score_explanation.TASK: KIND_CHAT,
    prefill.TASK: KIND_CHAT,
    cv_import_extract.CV_IMPORT_TASK: KIND_CHAT,
    parse.TECHNOLOGIES_TASK: KIND_CHAT,
    parse.PRESENCE_TASK: KIND_DECISION,
    parse.EXTRACTION_TASK: KIND_CHAT,
    parse.FAITHFUL_TASK: KIND_DECISION,
    rejections.REJECTION_TASK: KIND_DECISION,
    rejections.COMPANY_ROLE_TASK: KIND_CHAT,
    evaluate.TASK: KIND_DECISION,
    openrouter_routes.TASK_CHAT: KIND_CHAT,
    openrouter_routes.TASK_DECIDE: KIND_DECISION,
    **{f"{cv_generate.TASK_PREFIX}.relevance": KIND_DECISION},
    **{
        f"{cv_generate.TASK_PREFIX}.{step}": KIND_CHAT
        for step in ("context", "tech", "early", "categories", "summary", "role", "core_tech")
    },
}
"""Every LLM task the code calls, with its kind."""


def config(**overrides):
    data = {
        "providers": {
            "openrouter": {
                "type": "openrouter",
                "base_url": "https://o/api/v1",
                "decisions_url": "https://o/api/alpha/decisions",
                "api_key_env": "OPENROUTER_API_KEY",
            },
            "local": {"type": "openai_compatible", "base_url": "http://l/v1"},
        },
        "defaults": {
            "chat": {"provider": "openrouter", "model": "c/default", "temperature": 0.7, "extra": {"top_p": 1}},
            "decision": {"provider": "openrouter", "model": "j/default"},
        },
        "tasks": {
            "a": {"kind": "chat", "temperature": 0, "extra": {"seed": 3}},
            "b": {"kind": "chat", "provider": "local", "model": "llama", "max_tokens": 10},
            "d": {"kind": "decision", "model": "j/override"},
        },
    }
    for key, value in overrides.items():
        data[key] = value
    return parse_llm_config(data)


# --- shipped llm.toml ------------------------------------------------------------------------


def test_shipped_config_defines_exactly_the_tasks_in_code():
    shipped = load_llm_config(SHIPPED)
    assert set(shipped.tasks) == set(CODE_TASKS), "llm.toml and the code disagree on the LLM tasks"
    for task, kind in CODE_TASKS.items():
        resolved = shipped.resolve(task, kind)
        assert resolved.model
        assert shipped.tasks[task].description.strip(), f"{task} needs a description"


def test_shipped_config_keeps_previous_behaviour():
    """Moving the models/params into llm.toml must not change what is sent."""
    shipped = load_llm_config(SHIPPED)
    chat = {task: shipped.resolve(task, KIND_CHAT) for task, kind in CODE_TASKS.items() if kind == KIND_CHAT}
    decisions = [shipped.resolve(task, KIND_DECISION) for task, kind in CODE_TASKS.items() if kind == KIND_DECISION]
    assert {r.provider_name for r in [*chat.values(), *decisions]} == {"openrouter"}
    assert {r.model for r in chat.values()} == {"openai/gpt-4o-mini"}
    assert {r.model for r in decisions} == {"typesafe/jev-1.14"}
    assert {t: r.temperature for t, r in chat.items()} == {
        "candidate_profile.create": None,
        "job.score_explanation": 0.2,
        "work_history.prefill": 0,
        "cv_import.extract": 0,
        "parse.technologies": 0,
        "interview_steps.extract": 0,
        "gmail.company_role": 0,
        "api.chat": None,
        "cv.context": 0.3,
        "cv.tech": 0.3,
        "cv.early": 0.3,
        "cv.categories": 0.2,
        "cv.summary": 0.2,
        "cv.role": 0.2,
        "cv.core_tech": 0.2,
    }
    assert chat["job.score_explanation"].max_tokens == 200
    assert all(r.max_tokens is None for t, r in chat.items() if t != "job.score_explanation")


def test_shipped_local_provider_example_is_valid():
    """The commented ``[providers.local]`` example parses once uncommented."""
    text = SHIPPED.read_text()
    example = re.search(r"^# \[providers\.local\]\n((?:# .*\n)+)", text, re.MULTILINE)
    assert example is not None
    body = "\n".join(line.removeprefix("# ") for line in example.group(1).splitlines())
    provider = ProviderConfig.model_validate(tomllib.loads(body))
    assert provider.type == "openai_compatible" and not provider.supports_decisions


# --- resolve ---------------------------------------------------------------------------------


def test_resolve_merges_task_over_defaults():
    cfg = config()
    a = cfg.resolve("a", KIND_CHAT)
    assert (a.provider_name, a.model, a.temperature, a.max_tokens) == ("openrouter", "c/default", 0, None)
    assert a.extra == {"top_p": 1, "seed": 3}
    b = cfg.resolve("b", KIND_CHAT)
    assert (b.provider_name, b.provider.type, b.model, b.temperature, b.max_tokens) == (
        "local",
        "openai_compatible",
        "llama",
        0.7,
        10,
    )
    d = cfg.resolve("d", KIND_DECISION)
    assert (d.provider_name, d.model) == ("openrouter", "j/override")


def test_resolve_unknown_task_or_wrong_kind():
    cfg = config()
    with pytest.raises(LlmConfigError, match=r'add \[tasks."missing"\]'):
        cfg.resolve("missing", KIND_CHAT)
    with pytest.raises(LlmConfigError, match="is a decision task"):
        cfg.resolve("d", KIND_CHAT)


# --- validation ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"tasks": {"x": {"kind": "decision", "provider": "local"}}},
            "cannot answer decision tasks",
        ),
        (
            {"defaults": {"chat": {"provider": "nope", "model": "m"}, "decision": {"provider": "openrouter", "model": "j"}}},
            "unknown provider 'nope'",
        ),
        ({"tasks": {"x": {"kind": "embedding"}}}, "kind"),
        ({"tasks": {"x": {"kind": "chat", "temprature": 0}}}, "temprature"),
        ({"tasks": {"x": {"kind": "chat", "temperature": 3}}}, "temperature"),
        (
            {"providers": {"openrouter": {"type": "openrouter", "base_url": "https://o"}}},
            "needs decisions_url",
        ),
        (
            {
                "providers": {
                    "openrouter": {"type": "openrouter", "base_url": "https://o", "decisions_url": "https://o/d"},
                    "local": {"type": "openai_compatible", "base_url": "http://l", "decisions_url": "http://l/d"},
                }
            },
            "only apply to an openrouter provider",
        ),
    ],
)
def test_invalid_config_is_rejected(overrides, message):
    with pytest.raises(LlmConfigError, match=message):
        config(**overrides)


def test_load_reports_bad_toml_and_missing_file(tmp_path):
    bad = tmp_path / "llm.toml"
    bad.write_text("[providers\n")
    with pytest.raises(LlmConfigError, match="not valid TOML"):
        load_llm_config(bad)
    with pytest.raises(LlmConfigError, match="cannot read"):
        get_llm_config(tmp_path / "missing.toml")


def test_get_llm_config_reloads_when_the_file_changes(tmp_path):
    template = """
[providers.local]
type = "openai_compatible"
base_url = "http://l/v1"

[providers.openrouter]
type = "openrouter"
base_url = "https://o/api/v1"
decisions_url = "https://o/api/alpha/decisions"

[defaults.chat]
provider = "local"
model = "{model}"

[defaults.decision]
provider = "openrouter"
model = "j"

[tasks."cv.summary"]
kind = "chat"
"""
    path = tmp_path / "llm.toml"
    path.write_text(template.format(model="first"))
    assert get_llm_config(path).resolve("cv.summary", KIND_CHAT).model == "first"
    assert get_llm_config(path) is get_llm_config(path)  # cached while unchanged

    path.write_text(template.format(model="second"))
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    assert get_llm_config(path).resolve("cv.summary", KIND_CHAT).model == "second"


# --- keys and providers ----------------------------------------------------------------------


def test_api_key_from_settings_field_or_environment(monkeypatch):
    settings = Settings(openrouter_api_key="sk-or", local_llm_api_key="", cors_origins=[])
    provider = config().providers["openrouter"]
    assert api_key(provider, settings) == "sk-or"

    local = ProviderConfig(type="openai_compatible", base_url="http://l", api_key_env="LOCAL_LLM_API_KEY")
    monkeypatch.setenv("LOCAL_LLM_API_KEY", "from-env")
    assert api_key(local, settings) == ""  # the Settings field wins, even when empty

    other = ProviderConfig(type="openai_compatible", base_url="http://l", api_key_env="MY_GPU_BOX_KEY")
    monkeypatch.setenv("MY_GPU_BOX_KEY", "sk-gpu")
    assert api_key(other, settings) == "sk-gpu"
    assert api_key(ProviderConfig(type="openai_compatible", base_url="http://l"), settings) == ""


def test_build_providers():
    cfg = config()
    with_key = Settings(openrouter_api_key="sk", cors_origins=[])
    without_key = Settings(openrouter_api_key="", cors_origins=[])

    assert type(build_chat_provider("openrouter", cfg.providers["openrouter"], with_key)) is OpenRouterChat
    assert isinstance(build_decision_provider("openrouter", cfg.providers["openrouter"], with_key), JevDecisions)
    assert type(build_chat_provider("local", cfg.providers["local"], without_key)) is OpenAICompatibleChat
    with pytest.raises(OpenRouterNotConfigured, match="OPENROUTER_API_KEY is not set"):
        build_chat_provider("openrouter", cfg.providers["openrouter"], without_key)
    with pytest.raises(OpenRouterNotConfigured):
        build_decision_provider("openrouter", cfg.providers["openrouter"], without_key)
    with pytest.raises(LlmConfigError, match="cannot answer decision tasks"):
        build_decision_provider("local", cfg.providers["local"], without_key)


def test_openai_compatible_chat_text_variants():
    chat = OpenAICompatibleChat(config().providers["local"], "")
    assert chat.chat_text({"choices": [{"message": {"content": "a"}}]}) == "a"
    assert chat.chat_text({"choices": [{"message": {"content": [{"text": "a"}, {"text": "b"}]}}]}) == "ab"
    assert chat.chat_text({"choices": [{"message": {"content": None}}]}) == ""
