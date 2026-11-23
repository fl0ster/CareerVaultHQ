"""Response shapes of ``GET /api/dashboard/stats``, built by ``app.services.dashboard``."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

FlowKind = Literal["stage", "drop", "rejected", "pending", "accepted"]


class FlowNode(BaseModel):
    id: str
    label: str
    column: int
    """0 = scored jobs; each stage of the search one column further right."""
    kind: FlowKind
    """``stage``: the search continues from it; the others are where flows end — ``drop``
    (filtered out, passed on, closed), ``rejected``, ``pending`` (still waiting) or
    ``accepted``."""


class FlowLink(BaseModel):
    source: str
    target: str
    value: int


class Flow(BaseModel):
    """Sankey graph of the search: every scored job flows from left to right until it stops.
    Nodes and links without anything flowing through them are left out."""

    nodes: list[FlowNode]
    links: list[FlowLink]


class WeekCount(BaseModel):
    week_start: date
    """Monday of the week (UTC)."""
    count: int


class UpcomingRound(BaseModel):
    application_id: int
    job_title: str | None
    company: str | None
    title: str
    """Kind of round ("Technical", ...); empty when not named."""
    round: int
    """1-based round number."""
    scheduled_at: datetime


class DashboardStats(BaseModel):
    flow: Flow
    jobs_inbox: int
    active: int
    """Applications whose current state is not final."""
    interviews: int
    """Applications currently in the interview stage."""
    offers: int
    """Applications currently holding an offer."""
    responded: int
    """Applied applications that heard back (interview, rejection or offer)."""
    applied: int
    weekly_applied: list[WeekCount]
    """Applications sent (``APPLIED`` first reached) per week, oldest first."""
    upcoming: list[UpcomingRound]
    """Scheduled interview rounds from now on, soonest first."""
