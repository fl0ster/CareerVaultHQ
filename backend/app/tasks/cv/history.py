"""Turn relevance-scored work history into a coherent, non-overlapping CV timeline.

Pure functions, no I/O: the input is a list of :class:`Role` (one per ``work_history``
row, each with a ``relevance`` score in 0..1), the output a :class:`CoherentHistory` of
the roles to list in full (``main``), the roles to condense into a single "Additional
experience" block (``early``) and a human readable ``log`` of what was decided.

Three transformations are applied, in this order:

1. Irrelevant removal. Roles with relevance below ``irrelevant_relevance`` are moved
   straight to ``early``, no matter where they sit in the timeline and even if that
   leaves an employment gap in the main listing.

2. Overlap resolution. Longer, uninterrupted work periods are preferred. Whenever two
   roles overlap in time, the shorter one wins only when it is relevant (relevance >=
   ``high_relevance``) AND at least as relevant as the longer one; the longer role is then
   trimmed around it (keeping its larger remaining piece if it would be split). In every
   other case the shorter role is dropped, unless the months it alone covers would leave a
   gap of at least ``min_months``, in which case it is trimmed instead.

3. Early career split. Roles are listed newest first. At most ``max_entries`` are listed
   in full; every older role is moved to ``early``. Exceptionally relevant old roles
   (relevance >= ``exceptional_relevance``) are never moved: the cut is pushed back so
   that they, and everything newer, stay listed.

Months are handled as absolute indexes (``year * 12 + month - 1``) so trimming is plain
integer arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def month_index(value: date) -> int:
    return value.year * 12 + value.month - 1


def format_month(index: int) -> str:
    """``month_index(date(2020, 1, 1))`` -> ``"Jan 2020"``."""
    return f"{MONTH_NAMES[index % 12]} {index // 12}"


@dataclass
class Role:
    """One work history position on the month grid. ``current`` marks a position with no
    end date; its ``end`` is the current month and is printed as "Present" unless the
    overlap resolution trimmed it."""

    employer: str
    role: str
    start: int
    end: int
    relevance: float = 0.0
    location: str | None = None
    tech: list[str] = field(default_factory=list)
    context: str | None = None
    current: bool = False
    id: int | None = None

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"{self.label}: end before start")

    @classmethod
    def from_dates(
        cls,
        *,
        employer: str,
        role: str,
        date_start: date,
        date_end: date | None,
        today: date | None = None,
        **kwargs,
    ) -> Role:
        today = today or date.today()
        return cls(
            employer=employer,
            role=role,
            start=month_index(date_start),
            end=month_index(date_end or today),
            current=date_end is None,
            **kwargs,
        )

    @property
    def length(self) -> int:
        """Inclusive duration in months."""
        return self.end - self.start + 1

    @property
    def label(self) -> str:
        return f"{self.employer} / {self.role}"

    @property
    def date_start(self) -> str:
        return format_month(self.start)

    def date_end_label(self, today: date | None = None) -> str:
        """``"Present"`` for a current position whose end was not trimmed."""
        if self.current and self.end == month_index(today or date.today()):
            return "Present"
        return format_month(self.end)

    def overlaps(self, other: Role) -> bool:
        return self.start <= other.end and other.start <= self.end

    def to_dict(self, today: date | None = None) -> dict:
        """The shape the LLM prompts and the LaTeX renderer work with."""
        return {
            "date_start": self.date_start,
            "date_end": self.date_end_label(today),
            "employer": self.employer,
            "role": self.role,
            "location": self.location,
            "tech": ", ".join(self.tech),
            "context": self.context,
            "relevance": round(self.relevance, 4),
        }


@dataclass
class CoherentHistory:
    main: list[Role]
    """Roles to list in full, newest first."""
    early: list[Role]
    """Roles to condense into one block, newest first."""
    log: list[str] = field(default_factory=list)


def _newest_first(roles: list[Role]) -> list[Role]:
    return sorted(roles, key=lambda r: (r.start, r.end), reverse=True)


# --------------------------------------------------------------------------- steps


def split_irrelevant(
    roles: list[Role], irrelevant_relevance: float, log: list[str]
) -> tuple[list[Role], list[Role]]:
    """``(kept, irrelevant)``: roles below the threshold go to early history."""
    irrelevant = [r for r in roles if r.relevance < irrelevant_relevance]
    if irrelevant:
        log.append(
            f"moved {len(irrelevant)} irrelevant role(s) (relevance < {irrelevant_relevance}) "
            "to early history:"
        )
        for r in _newest_first(irrelevant):
            log.append(f"    - {r.label} [{r.relevance:.2f}]")
    kept = [r for r in roles if r.relevance >= irrelevant_relevance]
    return kept, irrelevant


def trim_around(loser: Role, winner: Role) -> bool:
    """Remove ``winner``'s interval from ``loser`` in place, keeping the larger remaining
    piece. Returns ``False`` when nothing is left."""
    before = (loser.start, winner.start - 1) if loser.start < winner.start else None
    after = (winner.end + 1, loser.end) if loser.end > winner.end else None
    candidates = [c for c in (before, after) if c is not None]
    if not candidates:
        return False
    loser.start, loser.end = max(candidates, key=lambda c: c[1] - c[0])
    return True


def pick_winner(a: Role, b: Role, high_relevance: float) -> tuple[Role, Role, bool]:
    """``(winner, loser, drop_loser)`` for two overlapping roles.

    The shorter role only wins when it is relevant and at least as relevant as the longer
    one; the longer one is then trimmed around it. Otherwise the longer period is preferred
    and the shorter role is dropped entirely.
    """
    shorter, longer = sorted((a, b), key=lambda r: (r.length, -r.relevance))
    if shorter.relevance >= high_relevance and shorter.relevance >= longer.relevance:
        return shorter, longer, False
    return longer, shorter, True


def covered(start: int, end: int, roles: list[Role]) -> bool:
    """True if every month in ``[start, end]`` is covered by at least one role."""
    month = start
    for r in sorted(roles, key=lambda r: r.start):
        if r.end < month:
            continue
        if r.start > month:
            return False
        month = r.end + 1
        if month > end:
            return True
    return month > end


def _span(role: Role) -> str:
    return f"{format_month(role.start)} - {format_month(role.end)}"


def resolve_overlaps(
    roles: list[Role], high_relevance: float, min_months: int, log: list[str]
) -> list[Role]:
    roles = list(roles)
    while True:
        roles.sort(key=lambda r: (r.start, r.end))
        pair = next(
            ((a, b) for i, a in enumerate(roles) for b in roles[i + 1 :] if a.overlaps(b)),
            None,
        )
        if pair is None:
            return roles

        winner, loser, drop_loser = pick_winner(*pair, high_relevance=high_relevance)
        old = _span(loser)
        scores = f"[{winner.relevance:.2f} vs {loser.relevance:.2f}]"

        if drop_loser:
            # Keep the history consecutive: only drop outright if the months the shorter
            # role sticks out by are covered by something else anyway.
            others = [r for r in roles if r is not loser]
            remainder = replace(loser)
            if (
                trim_around(remainder, winner)
                and remainder.length >= min_months
                and not covered(remainder.start, remainder.end, others)
            ):
                drop_loser = False
                log.append(
                    f"keeping  {loser.label}: dropping it would leave a gap ({_span(remainder)})"
                )

        if not drop_loser and trim_around(loser, winner):
            log.append(
                f"trimmed  {loser.label} ({old} -> {_span(loser)}) in favour of "
                f"{winner.label} {scores}"
            )
        else:
            roles.remove(loser)
            log.append(f"dropped  {loser.label} ({old}) in favour of {winner.label} {scores}")


def split_early_career(
    roles: list[Role], max_entries: int, exceptional_relevance: float, log: list[str]
) -> tuple[list[Role], list[Role]]:
    """``(kept, early)``: everything older than the newest ``max_entries`` roles. The cut
    is pushed back past any exceptionally relevant old role, so the early block is always
    the oldest consecutive run of non-exceptional roles."""
    newest_first = _newest_first(roles)
    cut = max_entries
    for i, role in enumerate(newest_first):
        if role.relevance >= exceptional_relevance:
            cut = max(cut, i + 1)

    early = newest_first[cut:]
    if early:
        log.append(
            f"moved {len(early)} early role(s) "
            f"({format_month(min(r.start for r in early))} - "
            f"{format_month(max(r.end for r in early))}) to early history:"
        )
        for r in early:
            log.append(f"    - {r.label} [{r.relevance:.2f}]")
    return newest_first[:cut], early


# ----------------------------------------------------------------------------- entry


def build_coherent_history(
    roles: list[Role],
    *,
    max_entries: int = 5,
    high_relevance: float = 0.3,
    exceptional_relevance: float = 0.6,
    irrelevant_relevance: float = 0.1,
    min_months: int = 3,
) -> CoherentHistory:
    """Apply the three transformations described in the module docstring. The input roles
    are copied, so the caller's objects are left untouched."""
    log: list[str] = []
    roles = [replace(r) for r in roles]

    kept, early = split_irrelevant(roles, irrelevant_relevance, log)
    kept = resolve_overlaps(kept, high_relevance, min_months, log)
    kept, older = split_early_career(kept, max_entries, exceptional_relevance, log)
    early += older

    main = _newest_first(kept)
    early = _newest_first(early)
    for r in main:
        log.append(
            f"  {format_month(r.start):>8} - {format_month(r.end):<8}  {r.relevance:.2f}  {r.label}"
        )
    for newer, older_role in zip(main, main[1:], strict=False):
        gap = newer.start - older_role.end - 1
        if gap > 0:
            log.append(f"  note: {gap}-month gap between {older_role.label} and {newer.label}")
    return CoherentHistory(main=main, early=early, log=log)
