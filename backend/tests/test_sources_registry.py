"""Discovery and contract validation of scraper plugin modules."""

import sys
import types

from app.tasks.scrape import sources


def _module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(f"app.tasks.scrape.sources.{name}")
    for key, value in attrs.items():
        setattr(mod, key, value)
    return mod


def _valid(name: str, **overrides) -> types.ModuleType:
    attrs = {
        "NAME": name.title(),
        "URL": f"https://{name}.example/jobs",
        "fetch_jobs": lambda: [],
        "parse_title": lambda html: "",
        "parse_company": lambda html: "",
        "parse_description": lambda html: "",
    }
    attrs.update(overrides)
    return _module(name, **attrs)


def test_validate_source_reports_every_problem():
    mod = _module("bad", NAME="", URL=42, fetch_jobs="not callable", parse_title=lambda h: "")

    problems = sources.validate_source(mod)

    assert problems == [
        "missing NAME",
        "missing URL",
        "missing fetch_jobs()",
        "missing parse_company()",
        "missing parse_description()",
    ]


def test_discover_sources_reports_import_and_contract_errors(monkeypatch):
    monkeypatch.setattr(sources, "get_available_sources", lambda: ["alpha", "broken", "crash"])
    monkeypatch.setitem(sys.modules, "app.tasks.scrape.sources.alpha", _valid("alpha"))
    monkeypatch.setitem(sys.modules, "app.tasks.scrape.sources.broken", _valid("broken", parse_title=None))

    def boom(name, package=None):
        if name.endswith(".crash"):
            raise ImportError("syntax error in crash.py")
        return sys.modules[name]

    monkeypatch.setattr(sources.importlib, "import_module", boom)

    infos = {info.key: info for info in sources.discover_sources()}

    assert infos["alpha"] == sources.SourceInfo(key="alpha", name="Alpha", url="https://alpha.example/jobs", error=None)
    assert infos["broken"].name == "Broken"
    assert infos["broken"].error == "missing parse_title()"
    assert infos["crash"].name == "crash"
    assert infos["crash"].url is None
    assert infos["crash"].error == "ImportError: syntax error in crash.py"
