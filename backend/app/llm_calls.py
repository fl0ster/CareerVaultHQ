"""Every OpenRouter call the app makes, in one place: which model it uses and why it exists.

Each call is a :class:`ChatCall` or :class:`DecisionCall` constant passed to ``OpenRouterService.chat`` /
``OpenRouterService.decide`` as ``call=``. Its ``source`` is the label stored in
``openrouter_calls.source`` (cost reports group by it).

Changing a model
----------------
* Development: edit the ``model`` of the constant below.
* Deployment (Docker): leave the code alone and write a TOML file whose ``[models]`` table maps
  a call ``key`` to a model id. Its path is ``OPENROUTER_MODELS_FILE`` (``/data/llm_models.toml``
  in docker-compose, ``backend/llm_models.toml`` in development). See
  ``backend/llm_models.example.toml`` for every key. The file is read once per process, so
  restart the API and worker after editing it.

Adding a call
-------------
1. Add a :class:`ChatCall` (``OpenRouterService.chat``) or :class:`DecisionCall`
   (``OpenRouterService.decide``) constant here (unique ``key``, ``source``, default ``model``,
   ``purpose``, ``used_in``) and list it in :data:`ALL_CALLS`. The class fixes the kind of
   call; only the model can be changed, here or in the override file.
2. Pass it as ``call=`` to the service; never hardcode a model id or ``source`` string elsewhere.
3. Add the key (commented out) to ``backend/llm_models.example.toml``.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from app.config import Settings

DEFAULT_CHAT_MODEL = "openai/gpt-4o-mini"
"""General-purpose chat completion model."""
DEFAULT_DECISION_MODEL = "typesafe/jev-1.14"
"""Jev Decisions API model (https://openrouter.ai/docs/guides/community/jev)."""


@dataclass(frozen=True, slots=True)
class LlmCall:
    """Fields shared by both kinds of call. Not used directly: a call is either a
    :class:`ChatCall` or a :class:`DecisionCall`, and the class fixes which endpoint it uses
    (only the model is configurable)."""

    kind: ClassVar[str]
    """``chat`` or ``decision``; fixed by the subclass, never configured."""

    key: str
    """Unique id; also the key used in the TOML override file."""
    source: str
    """Label stored in ``openrouter_calls.source``."""
    model: str
    """Default OpenRouter model id."""
    purpose: str
    """What the call does and why."""
    used_in: str
    """Module that makes the call."""

    def __post_init__(self) -> None:
        if type(self) is LlmCall:
            raise TypeError("use ChatCall or DecisionCall, not LlmCall")


@dataclass(frozen=True, slots=True)
class ChatCall(LlmCall):
    """Free-text chat completion: only ``OpenRouterService.chat`` accepts it."""

    kind: ClassVar[str] = "chat"


@dataclass(frozen=True, slots=True)
class DecisionCall(LlmCall):
    """Jev Decisions API call (typed answers with probabilities): only
    ``OpenRouterService.decide`` accepts it."""

    kind: ClassVar[str] = "decision"


# --- Candidate profile ----------------------------------------------------------------------

CANDIDATE_PROFILE = ChatCall(
    key="candidate_profile",
    source="candidate_profile.create",
    model=DEFAULT_CHAT_MODEL,
    purpose="Summarise the candidate's details and work history into the profile text that jobs are scored against.",
    used_in="app.services.candidate_profile",
)

# --- Job parsing (scraped / manual job descriptions) ----------------------------------------

INTERVIEW_STEPS_PRESENCE = DecisionCall(
    key="interview_steps_presence",
    source="tasks.parse.interview_steps",
    model=DEFAULT_DECISION_MODEL,
    purpose="Yes/no: does the text (job description or recruiter e-mail) describe the recruitment process at all? "
    "Gates the extraction below.",
    used_in="app.tasks.parse.parse (also app.tasks.gmail.interview_steps)",
)

INTERVIEW_STEPS_EXTRACT = ChatCall(
    key="interview_steps_extract",
    source="tasks.parse.interview_steps",
    model=DEFAULT_CHAT_MODEL,
    purpose="Extract the ordered interview stages (title, duration) from the text as JSON.",
    used_in="app.tasks.parse.parse (also app.tasks.gmail.interview_steps)",
)

INTERVIEW_STEPS_FAITHFUL = DecisionCall(
    key="interview_steps_faithful",
    source="tasks.parse.interview_steps",
    model=DEFAULT_DECISION_MODEL,
    purpose="Yes/no: are the extracted interview stages faithful to the text? Unfaithful extractions are dropped.",
    used_in="app.tasks.parse.parse (also app.tasks.gmail.interview_steps)",
)

PARSE_TECHNOLOGIES = ChatCall(
    key="parse_technologies",
    source="tasks.parse.technologies",
    model=DEFAULT_CHAT_MODEL,
    purpose="List the technologies named in a job description, each with a quote that is checked against the text.",
    used_in="app.tasks.parse.parse",
)

# --- Job evaluation -------------------------------------------------------------------------

JOB_EVALUATION = DecisionCall(
    key="job_evaluation",
    source="tasks.evaluate",
    model=DEFAULT_DECISION_MODEL,
    purpose="Probability that a parsed job is a good match for the candidate profile (the job's score).",
    used_in="app.tasks.evaluate.evaluate",
)

JOB_SCORE_EXPLANATION = ChatCall(
    key="job_score_explanation",
    source="api.jobs.explanation",
    model=DEFAULT_CHAT_MODEL,
    purpose="Short human-readable explanation of why a job got its score (on demand from the job page).",
    used_in="app.services.score_explanation",
)

# --- Work history ---------------------------------------------------------------------------

WORK_HISTORY_PREFILL = ChatCall(
    key="work_history_prefill",
    source="tasks.work_history.prefill",
    model=DEFAULT_CHAT_MODEL,
    purpose="Prefill a new work history entry (description, technologies) from the accepted job's description.",
    used_in="app.tasks.work_history.prefill",
)

# --- Work journal ---------------------------------------------------------------------------

JOURNAL_MONTH_SUMMARY = ChatCall(
    key="journal_month_summary",
    source="services.work_journal.month",
    model=DEFAULT_CHAT_MODEL,
    purpose="Polish one month of a position's raw work-journal notes into a summary, accomplishments and "
    "technologies, using only facts from the notes.",
    used_in="app.services.work_journal",
)

JOURNAL_ROLE_CONTEXT = ChatCall(
    key="journal_role_context",
    source="services.work_journal.context",
    model=DEFAULT_CHAT_MODEL,
    purpose="Write a position's CV description from its monthly work-journal summaries (used while the user's "
    "own description is blank).",
    used_in="app.services.work_journal",
)

JOURNAL_FAITHFUL = DecisionCall(
    key="journal_faithful",
    source="services.work_journal.faithful",
    model=DEFAULT_DECISION_MODEL,
    purpose="Yes/no: is every statement of a generated journal summary or description supported by its "
    "source notes? Unfaithful texts are retried, then discarded.",
    used_in="app.services.work_journal",
)

# --- Gmail monitor --------------------------------------------------------------------------

GMAIL_REJECTION = DecisionCall(
    key="gmail_rejection",
    source="tasks.gmail_rejections",
    model=DEFAULT_DECISION_MODEL,
    purpose="Probability that an e-mail is a rejection of one of the candidate's applications.",
    used_in="app.tasks.gmail.rejections",
)

MAIL_COMPANY_AND_ROLE = ChatCall(
    key="mail_company_and_role",
    source="tasks.gmail_rejections",
    model=DEFAULT_CHAT_MODEL,
    purpose="Read the company and role an e-mail is about, to match it to an application.",
    used_in="app.tasks.gmail.rejections (also app.tasks.gmail.interview_steps)",
)

# --- CV import ------------------------------------------------------------------------------

CV_IMPORT = ChatCall(
    key="cv_import",
    source="tasks.cv_import",
    model=DEFAULT_CHAT_MODEL,
    purpose="Extract candidate details and work history as JSON from the text of an uploaded CV PDF.",
    used_in="app.tasks.cv_import.extract",
)

# --- CV generation (tailoring the work history to one job) ----------------------------------

CV_RELEVANCE = DecisionCall(
    key="cv_relevance",
    source="tasks.cv.relevance",
    model=DEFAULT_DECISION_MODEL,
    purpose="Probability that a past role is relevant to the target job; decides which roles are listed in full.",
    used_in="app.tasks.cv.generate",
)

CV_CONTEXT = ChatCall(
    key="cv_context",
    source="tasks.cv.context",
    model=DEFAULT_CHAT_MODEL,
    purpose="Rewrite a role's project context paragraph for the target job.",
    used_in="app.tasks.cv.generate",
)

CV_TECH = ChatCall(
    key="cv_tech",
    source="tasks.cv.tech",
    model=DEFAULT_CHAT_MODEL,
    purpose="Select and order a role's technologies for the target job.",
    used_in="app.tasks.cv.generate",
)

CV_EARLY = ChatCall(
    key="cv_early",
    source="tasks.cv.early",
    model=DEFAULT_CHAT_MODEL,
    purpose="Condense an older / less relevant role into a one-line 'Additional experience' entry.",
    used_in="app.tasks.cv.generate",
)

CV_CATEGORIES = ChatCall(
    key="cv_categories",
    source="tasks.cv.categories",
    model=DEFAULT_CHAT_MODEL,
    purpose="Group the CV's technologies into skill categories.",
    used_in="app.tasks.cv.generate",
)

CV_SUMMARY = ChatCall(
    key="cv_summary",
    source="tasks.cv.summary",
    model=DEFAULT_CHAT_MODEL,
    purpose="Write the CV's summary paragraph tailored to the target job.",
    used_in="app.tasks.cv.generate",
)

CV_ROLE = ChatCall(
    key="cv_role",
    source="tasks.cv.role",
    model=DEFAULT_CHAT_MODEL,
    purpose="Choose the headline role title shown at the top of the CV.",
    used_in="app.tasks.cv.generate",
)

CV_CORE_TECH = ChatCall(
    key="cv_core_tech",
    source="tasks.cv.core_tech",
    model=DEFAULT_CHAT_MODEL,
    purpose="Pick the core technologies highlighted in the CV header.",
    used_in="app.tasks.cv.generate",
)

# --- API playground (POST /api/openrouter/chat|decide) -------------------------------------

PLAYGROUND_CHAT = ChatCall(
    key="playground_chat",
    source="api.openrouter.chat",
    model=DEFAULT_CHAT_MODEL,
    purpose="Ad-hoc chat request through the API; the request may name its own model and source.",
    used_in="app.api.routes.openrouter",
)

PLAYGROUND_DECIDE = DecisionCall(
    key="playground_decide",
    source="api.openrouter.decide",
    model=DEFAULT_DECISION_MODEL,
    purpose="Ad-hoc decision request through the API; the request may name its own model and source.",
    used_in="app.api.routes.openrouter",
)

ALL_CALLS: tuple[LlmCall, ...] = (
    CANDIDATE_PROFILE,
    INTERVIEW_STEPS_PRESENCE,
    INTERVIEW_STEPS_EXTRACT,
    INTERVIEW_STEPS_FAITHFUL,
    PARSE_TECHNOLOGIES,
    JOB_EVALUATION,
    JOB_SCORE_EXPLANATION,
    WORK_HISTORY_PREFILL,
    JOURNAL_MONTH_SUMMARY,
    JOURNAL_ROLE_CONTEXT,
    JOURNAL_FAITHFUL,
    GMAIL_REJECTION,
    MAIL_COMPANY_AND_ROLE,
    CV_IMPORT,
    CV_RELEVANCE,
    CV_CONTEXT,
    CV_TECH,
    CV_EARLY,
    CV_CATEGORIES,
    CV_SUMMARY,
    CV_ROLE,
    CV_CORE_TECH,
    PLAYGROUND_CHAT,
    PLAYGROUND_DECIDE,
)

CALLS_BY_KEY: dict[str, LlmCall] = {call.key: call for call in ALL_CALLS}


# --- Overrides ------------------------------------------------------------------------------


@lru_cache
def load_model_overrides(path: Path) -> dict[str, str]:
    """``{key: model}`` from the ``[models]`` table of the TOML file at ``path``; empty when the
    file does not exist. Raises ``ValueError`` for invalid TOML, unknown keys or non-string
    values, so a typo fails loudly instead of being ignored."""
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path}: invalid TOML: {exc}") from exc
    models = data.get("models", {})
    if not isinstance(models, dict):
        raise ValueError(f'{path}: [models] must be a table of key = "model"')
    unknown = sorted(set(models) - CALLS_BY_KEY.keys())
    if unknown:
        raise ValueError(f"{path}: unknown OpenRouter call key(s) {unknown}; valid keys: {sorted(CALLS_BY_KEY)}")
    bad = sorted(key for key, model in models.items() if not isinstance(model, str) or not model.strip())
    if bad:
        raise ValueError(f"{path}: model for {bad} must be a non-empty string")
    return {key: model.strip() for key, model in models.items()}


def resolve_model(call: LlmCall, settings: Settings) -> str:
    """The model to use for ``call``: the override file's entry, else the default."""
    return load_model_overrides(settings.openrouter_models_file).get(call.key, call.model)
