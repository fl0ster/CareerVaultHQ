from dataclasses import dataclass
from datetime import date

from app.models import WorkHistoryEntry
from app.services.career import close_previous_role, previous_role_ids, tenure_ids


@dataclass
class Entry:
    id: int
    employer: str
    date_start: date
    transition: str | None = None
    kind: str = "job"


def test_links_the_latest_earlier_role_at_the_same_employer():
    entries = [
        Entry(1, "Acme Sp. z o.o.", date(2015, 1, 1)),
        Entry(2, "Other", date(2017, 1, 1)),
        Entry(3, "acme sp z o o", date(2019, 1, 1), "promotion"),
        Entry(4, "ACME  Sp. z o.o.", date(2022, 1, 1), "role_change"),
    ]
    assert previous_role_ids(entries) == {3: 1, 4: 3}
    assert tenure_ids(entries) == {1: 1, 2: 2, 3: 1, 4: 1}


def test_no_link_without_a_transition_or_an_earlier_role():
    entries = [
        Entry(1, "Acme", date(2015, 1, 1)),
        Entry(2, "Acme", date(2019, 1, 1)),  # a return to Acme, not a promotion
        Entry(3, "Other", date(2020, 1, 1), "promotion"),  # nothing earlier at Other
        Entry(4, "Acme", date(2014, 1, 1), "promotion", kind="education"),
    ]
    assert previous_role_ids(entries) == {}
    assert tenure_ids(entries) == {1: 1, 2: 2, 3: 3}


def test_same_start_date_is_ordered_by_id():
    entries = [Entry(2, "Acme", date(2020, 1, 1), "promotion"), Entry(1, "Acme", date(2020, 1, 1))]
    assert previous_role_ids(entries) == {2: 1}


def _job(session, start, end=None, transition=None, employer="Acme"):
    entry = WorkHistoryEntry(date_start=start, date_end=end, employer=employer, role="Dev", tech=[], transition=transition)
    session.add(entry)
    session.flush()
    return entry


def test_close_previous_role_ends_an_ongoing_predecessor(db_session):
    first = _job(db_session, date(2019, 1, 1))
    second = _job(db_session, date(2022, 3, 15), transition="promotion")
    assert close_previous_role(db_session, second) is first
    assert first.date_end == date(2022, 3, 14)


def test_close_previous_role_never_ends_before_the_start(db_session):
    first = _job(db_session, date(2022, 3, 1))
    second = _job(db_session, date(2022, 3, 1), transition="role_change")
    close_previous_role(db_session, second)
    assert first.date_end == date(2022, 3, 1)


def test_close_previous_role_leaves_other_roles_alone(db_session):
    ended = _job(db_session, date(2019, 1, 1), end=date(2020, 1, 1))
    later = _job(db_session, date(2021, 1, 1), transition="promotion")
    assert close_previous_role(db_session, later) is None
    assert ended.date_end == date(2020, 1, 1)

    other = _job(db_session, date(2019, 1, 1), employer="Other")
    new_job = _job(db_session, date(2023, 1, 1))  # no transition
    assert close_previous_role(db_session, new_job) is None
    assert other.date_end is None
