"""Explaining a job's relevance score in a few sentences, on the user's request.

The score itself comes from the decisions API (``app.tasks.evaluate``), which answers with
a probability only. ``explain_evaluation`` asks the chat model why the job scored the way
it did against the candidate profile the score was made with, and stores the answer on the
``JobEvaluation`` row: one explanation per (parsed job, candidate profile) pair, reused
until the work history changes and the job is re-scored.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import JobEvaluation
from app.services.openrouter import OpenRouterError, OpenRouterService

SOURCE = "api.jobs.explanation"
"""``openrouter_calls.source`` label for explanation calls."""
TASK = "job.score_explanation"
"""``llm.toml`` task: model and parameters of the explanation call."""

MAX_DESCRIPTION_CHARS = 12_000
"""Longer job descriptions are cut: the requirements are almost always near the top."""

SYSTEM = (
    "You explain to a job seeker why a job posting was scored as a good or poor match for "
    "them. You get the candidate's profile, the job posting and the verdict. Answer in 2-3 "
    "short sentences (at most 60 words), addressing the candidate as 'you'. Name the concrete "
    "experience, skills or technologies of the candidate that match the job's requirements, "
    "and the required ones the candidate is missing. Base the answer on the verdict: for a "
    "good match lead with what matches, for a poor match lead with what is missing. Ignore "
    "salary and location. Plain text only: no lists, headings or markdown."
)


def _verdict(probability: float, threshold: float) -> str:
    if probability >= threshold:
        strength = "a strong" if probability >= (1 + threshold) / 2 else "a reasonable"
        return f"{strength} match ({probability:.0%} likely to be a good fit)"
    strength = "a poor" if probability < threshold / 2 else "a weak"
    return f"{strength} match ({probability:.0%} likely to be a good fit)"


def build_prompt(evaluation: JobEvaluation, threshold: float) -> str:
    parsed = evaluation.job_parse_result
    description = (parsed.description or "")[:MAX_DESCRIPTION_CHARS]
    company = parsed.company.name if parsed.company is not None else "unknown"
    return (
        f"Candidate profile:\n{evaluation.candidate_profile.content}\n\n"
        f"Job title: {parsed.title or 'unknown'}\n"
        f"Company: {company}\n"
        f"Job description:\n{description}\n\n"
        f"Verdict: {_verdict(evaluation.match_probability, threshold)}.\n"
        "Explain why."
    )


def explain_evaluation(session: Session, service: OpenRouterService, evaluation: JobEvaluation, threshold: float) -> str:
    """The stored explanation of ``evaluation``, generated (and saved) first when missing.
    Raises ``OpenRouterError`` when the chat call fails."""
    if evaluation.explanation:
        return evaluation.explanation
    reply = service.chat(build_prompt(evaluation, threshold), system=SYSTEM, task=TASK, source=SOURCE)
    text = " ".join(reply.text.split())
    if not text:
        raise OpenRouterError("the model returned an empty explanation")
    evaluation.explanation = text
    session.commit()
    return text
