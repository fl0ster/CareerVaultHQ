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
    history = build_coherent_history(roles, min_entries=2)
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


def test_early_career_split_never_lists_more_than_max_entries():
    roles = [role(f"R{i}", date(2010 + 2 * i, 1, 1), date(2011 + 2 * i, 12, 1), 0.3) for i in range(7)]
    roles[0].relevance = 0.95  # oldest role, very relevant: still condensed
    history = build_coherent_history(roles, max_entries=3)
    assert [r.employer for r in history.main] == ["R6", "R5", "R4"]
    assert [r.employer for r in history.early] == ["R3", "R2", "R1", "R0"]


def test_min_entries_backfills_most_relevant_irrelevant_roles():
    roles = [
        role("Old", date(2010, 1, 1), date(2011, 12, 1), 0.05),
        role("Mid", date(2012, 1, 1), date(2015, 12, 1), 0.15),
        role("Low", date(2016, 1, 1), date(2019, 12, 1), 0.08),
        role("Fit", date(2020, 1, 1), None, 0.9),
    ]
    history = build_coherent_history(roles, max_entries=5, min_entries=3, irrelevant_relevance=0.2)
    # Only "Fit" is relevant; the two most relevant of the rest are listed anyway.
    assert [r.employer for r in history.main] == ["Fit", "Low", "Mid"]
    assert [r.employer for r in history.early] == ["Old"]
    assert any("minimum is 3" in line for line in history.log)

    # min_entries never exceeds max_entries, and a short history is listed as-is.
    history = build_coherent_history(roles, max_entries=2, min_entries=3, irrelevant_relevance=0.2)
    assert [r.employer for r in history.main] == ["Fit", "Mid"]
    history = build_coherent_history(roles[3:], max_entries=5, min_entries=3)
    assert [r.employer for r in history.main] == ["Fit"]


def test_condensed_roles_never_overlap_listed_or_each_other():
    roles = [
        role("Main", date(2018, 1, 1), None, 0.9),
        # Irrelevant side job running into the listed role: trimmed to before it.
        role("Side", date(2016, 1, 1), date(2019, 6, 1), 0.05),
        # Irrelevant job entirely inside the listed role: dropped.
        role("Inside", date(2020, 1, 1), date(2020, 12, 1), 0.05),
        # Two irrelevant early jobs overlapping each other: the longer wins.
        role("EarlyLong", date(2010, 1, 1), date(2014, 12, 1), 0.05),
        role("EarlyShort", date(2013, 1, 1), date(2013, 6, 1), 0.1),
    ]
    history = build_coherent_history(roles, min_entries=1, irrelevant_relevance=0.2)
    assert [r.employer for r in history.main] == ["Main"]
    assert [r.employer for r in history.early] == ["Side", "EarlyLong"]
    side = history.early[0]
    assert (side.date_start, side.date_end_label(TODAY)) == ("Jan 2016", "Dec 2017")
    shown = history.main + history.early
    for a in shown:
        for b in shown:
            assert a is b or not a.overlaps(b), (a.label, b.label)


def test_condensed_role_shorter_than_min_months_is_dropped():
    roles = [
        role("Main", date(2018, 1, 1), None, 0.9),
        # Irrelevant job trimmed down to a 2-month stub by the listed role: dropped, a gap
        # is better than a stub that needs explaining.
        role("Stub", date(2017, 11, 1), date(2018, 6, 1), 0.05),
        # Already shorter than the minimum, even without trimming: dropped too.
        role("Tiny", date(2015, 1, 1), date(2015, 2, 1), 0.05),
        role("Old", date(2012, 1, 1), date(2014, 12, 1), 0.05),
    ]
    history = build_coherent_history(roles, min_entries=1, irrelevant_relevance=0.2, min_months=3)
    assert [r.employer for r in history.main] == ["Main"]
    assert [r.employer for r in history.early] == ["Old"]
    assert sum("shorter than 3 months" in line for line in history.log) == 2


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
