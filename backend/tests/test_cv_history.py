from datetime import date

from app.tasks.cv.history import Role, build_coherent_history, format_month, month_index

TODAY = date(2026, 11, 15)


def role(employer, start, end, relevance, *, today=TODAY, **kwargs) -> Role:
    return Role.from_dates(
        employer=employer,
        role=f"{employer} role",
        date_start=start,
        date_end=end,
        today=today,
        relevance=relevance,
        **kwargs,
    )


def test_month_index_roundtrip_and_present():
    r = role("Now", date(2025, 5, 1), None, 0.9)
    assert r.current
    assert r.date_start == "May 2025"
    assert r.date_end_label(TODAY) == "Present"
    assert format_month(month_index(date(2020, 1, 1))) == "Jan 2020"
    assert r.length == 19  # May 2025 .. Nov 2026 inclusive


def test_irrelevant_roles_go_to_early_even_if_it_leaves_a_gap():
    roles = [
        role("A", date(2024, 1, 1), None, 0.9),
        role("B", date(2022, 1, 1), date(2023, 12, 1), 0.05),
        role("C", date(2020, 1, 1), date(2021, 12, 1), 0.8),
    ]
    history = build_coherent_history(roles)
    assert [r.employer for r in history.main] == ["A", "C"]
    assert [r.employer for r in history.early] == ["B"]
    assert any("gap" in line for line in history.log)


def test_shorter_relevant_role_wins_overlap_and_longer_is_trimmed():
    roles = [
        role("Long", date(2020, 1, 1), date(2023, 12, 1), 0.4),
        role("Short", date(2021, 6, 1), date(2021, 12, 1), 0.9),
    ]
    history = build_coherent_history(roles)
    # The larger remaining piece of "Long" (Jan 2022 - Dec 2023) is kept, which now
    # starts after "Short", so it is listed first.
    assert [r.employer for r in history.main] == ["Long", "Short"]
    long = history.main[0]
    assert (long.date_start, long.date_end_label(TODAY)) == ("Jan 2022", "Dec 2023")
    assert any(line.startswith("trimmed") for line in history.log)


def test_shorter_less_relevant_role_is_dropped():
    roles = [
        role("Long", date(2020, 1, 1), date(2023, 12, 1), 0.8),
        role("Short", date(2021, 6, 1), date(2021, 12, 1), 0.5),
    ]
    history = build_coherent_history(roles)
    assert [r.employer for r in history.main] == ["Long"]
    assert history.early == []
    assert any(line.startswith("dropped") for line in history.log)


def test_losing_role_is_trimmed_not_dropped_when_it_alone_covers_months():
    roles = [
        role("Long", date(2020, 1, 1), date(2022, 12, 1), 0.8),
        role("Short", date(2022, 6, 1), date(2023, 8, 1), 0.5),  # sticks out by 8 months
    ]
    history = build_coherent_history(roles, min_months=3)
    assert [r.employer for r in history.main] == ["Short", "Long"]
    short = history.main[0]
    assert (short.date_start, short.date_end_label(TODAY)) == ("Jan 2023", "Aug 2023")
    assert not short.current


def test_trimmed_current_role_is_no_longer_present():
    roles = [
        role("Long", date(2024, 1, 1), None, 0.9),
        role("Side", date(2023, 1, 1), None, 0.5),  # longer, less relevant -> dropped? no:
    ]
    # "Side" is the longer one (Jan 2023 - Nov 2026) and more... less relevant, but the
    # shorter "Long" is relevant (>= 0.3) and at least as relevant, so it wins and "Side"
    # is trimmed to the part before it, losing its "Present" end.
    history = build_coherent_history(roles)
    side = next(r for r in history.main if r.employer == "Side")
    assert side.date_end_label(TODAY) == "Dec 2023"


def test_early_career_split_keeps_exceptional_old_roles():
    roles = [
        role(f"R{i}", date(2010 + 2 * i, 1, 1), date(2011 + 2 * i, 12, 1), 0.3) for i in range(7)
    ]
    roles[0].relevance = 0.95  # oldest role, exceptionally relevant
    history = build_coherent_history(roles, max_entries=3)
    # Cut pushed back past the exceptional role: everything stays listed.
    assert len(history.main) == 7
    assert history.early == []

    roles[0].relevance = 0.3
    history = build_coherent_history(roles, max_entries=3)
    assert [r.employer for r in history.main] == ["R6", "R5", "R4"]
    assert [r.employer for r in history.early] == ["R3", "R2", "R1", "R0"]


def test_input_roles_are_not_mutated():
    roles = [
        role("Long", date(2020, 1, 1), date(2023, 12, 1), 0.4),
        role("Short", date(2021, 6, 1), date(2021, 12, 1), 0.9),
    ]
    build_coherent_history(roles)
    assert roles[0].date_start == "Jan 2020"
    assert roles[0].date_end_label(TODAY) == "Dec 2023"


def test_to_dict_shape():
    r = role("Acme", date(2020, 1, 1), date(2021, 6, 1), 0.123456, tech=["A", "B"], context="x")
    assert r.to_dict(TODAY) == {
        "date_start": "Jan 2020",
        "date_end": "Jun 2021",
        "employer": "Acme",
        "role": "Acme role",
        "location": None,
        "tech": "A, B",
        "context": "x",
        "relevance": 0.1235,
    }
