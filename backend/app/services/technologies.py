"""Technology names: one canonical comparison key per technology.

Job listings and the work history spell the same technology in many ways ("React.js",
"ReactJS", "react"; "Postgres", "PostgreSQL"; "k8s", "Kubernetes"). ``technology_key``
maps every spelling to one lower-case key, so a job's ``JobParseResult.technologies``
(each entry carries its ``key``) can be checked against ``WorkHistoryEntry.tech`` with
plain set operations::

    from app.services.technologies import match_technologies

    match = match_technologies(parsed.technologies, [e.tech for e in work_history])
    match.matched, match.missing
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

ALIASES: dict[str, str] = {
    # JavaScript ecosystem
    "js": "javascript",
    "ecmascript": "javascript",
    "es6": "javascript",
    "ts": "typescript",
    "reactjs": "react",
    "react js": "react",
    "react.js": "react",
    "nextjs": "next.js",
    "next": "next.js",
    "vuejs": "vue",
    "vue.js": "vue",
    "vue js": "vue",
    "nuxtjs": "nuxt",
    "nuxt.js": "nuxt",
    "angularjs": "angular",
    "angular.js": "angular",
    "nodejs": "node.js",
    "node": "node.js",
    "node js": "node.js",
    "expressjs": "express",
    "express.js": "express",
    "nestjs": "nest.js",
    "nest": "nest.js",
    # Backend / languages
    "golang": "go",
    "c sharp": "c#",
    "csharp": "c#",
    "dotnet": ".net",
    "net": ".net",
    ".net core": ".net",
    "dotnet core": ".net",
    "asp.net core": "asp.net",
    "cpp": "c++",
    "python3": "python",
    "python 3": "python",
    "py": "python",
    "java ee": "jakarta ee",
    "j2ee": "jakarta ee",
    "spring boot": "spring boot",
    "springboot": "spring boot",
    "ror": "ruby on rails",
    "rails": "ruby on rails",
    "objective c": "objective-c",
    "objc": "objective-c",
    # Data stores
    "postgres": "postgresql",
    "postgre": "postgresql",
    "psql": "postgresql",
    "mongo": "mongodb",
    "ms sql": "sql server",
    "mssql": "sql server",
    "microsoft sql server": "sql server",
    "elastic": "elasticsearch",
    "elastic search": "elasticsearch",
    "dynamo": "dynamodb",
    "redis cache": "redis",
    # Cloud / ops
    "k8s": "kubernetes",
    "amazon web services": "aws",
    "google cloud": "gcp",
    "google cloud platform": "gcp",
    "microsoft azure": "azure",
    "azure cloud": "azure",
    "github actions": "github actions",
    "gh actions": "github actions",
    "ci/cd": "ci/cd",
    "cicd": "ci/cd",
    "docker compose": "docker compose",
    "docker-compose": "docker compose",
    "tf": "terraform",
    # Game dev / misc
    "unity3d": "unity",
    "unity 3d": "unity",
    "ue": "unreal engine",
    "ue4": "unreal engine",
    "ue5": "unreal engine",
    "unreal": "unreal engine",
    "rest api": "rest",
    "restful": "rest",
    "rest apis": "rest",
    "restful api": "rest",
    "graph ql": "graphql",
    "rabbit mq": "rabbitmq",
    "apache kafka": "kafka",
    "apache spark": "spark",
    "pyspark": "spark",
    "sklearn": "scikit-learn",
    "scikit learn": "scikit-learn",
    "tensor flow": "tensorflow",
    "html5": "html",
    "css3": "css",
}
"""Spelling (already lower-cased, whitespace-collapsed) -> canonical key."""

_VERSION_SUFFIX = re.compile(r"\s+v?\d+(\.\d+)*(\.x)?\+?$")
"""Trailing version numbers ("Java 17", "Python 3.11", "Angular 15"); a space must precede
the version so names like "S3" or "EC2" are kept."""


def technology_key(name: str) -> str:
    """The canonical comparison key of a technology name ("" for a blank name)."""
    key = " ".join(name.lower().replace("_", " ").split())
    if not key:
        return ""
    if key in ALIASES:
        return ALIASES[key]
    stripped = _VERSION_SUFFIX.sub("", key)
    if stripped:
        key = stripped
    key = key.replace("-js", "js")
    return ALIASES.get(key, key)


def alias_spellings(key: str) -> set[str]:
    """Every known lower-case spelling of ``key`` (the key itself included)."""
    return {key} | {alias for alias, target in ALIASES.items() if target == key}


def dedupe_technologies(names: Iterable[str]) -> list[dict[str, str]]:
    """``[{"name": <first spelling seen>, "key": technology_key(name)}, ...]`` with one
    entry per key, in input order."""
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for name in names:
        clean = " ".join(name.split())
        key = technology_key(clean)
        if key and key not in seen:
            seen.add(key)
            out.append({"name": clean, "key": key})
    return out


@dataclass(frozen=True)
class TechnologyMatch:
    matched: list[str]
    """Names of the job's technologies the candidate has used."""
    missing: list[str]
    """Names of the job's technologies absent from the work history."""

    @property
    def ratio(self) -> float | None:
        total = len(self.matched) + len(self.missing)
        return len(self.matched) / total if total else None


def match_technologies(job_technologies: Iterable[dict] | None, history_tech: Iterable[Iterable[str]]) -> TechnologyMatch:
    """Compare ``JobParseResult.technologies`` with the ``tech`` lists of the work history
    entries, by canonical key."""
    known = {technology_key(name) for tech in history_tech for name in tech}
    matched: list[str] = []
    missing: list[str] = []
    for item in job_technologies or []:
        key = item.get("key") or technology_key(item.get("name", ""))
        (matched if key in known else missing).append(item.get("name") or key)
    return TechnologyMatch(matched, missing)
