import pytest

from app.tasks.scrape import generic
from app.tasks.scrape.sources import skillshot
from app.tasks.scrape.work_mode import work_mode_from_jobposting, work_mode_from_text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("zdalnie", "remote"),
        ("Polska / zdalnie", "remote"),
        ("100% remote", "remote"),
        ("Work from home, flexible hours", "remote"),
        ("Warszawa (model hybrydowy)", "hybrid"),
        ("Hybrid: 2 days a week in the office", "hybrid"),
        ("Wrocław / Hybrydowo / Zdalnie", "hybrid"),
        ("Remote or on-site in Kraków", "hybrid"),
        ("ON-SITE in Poznań", "office"),
        ("Szczecin - Stacjonarnie", "office"),
        ("Pracy stacjonarnej w biurze w centrum Łodzi", "office"),
        ("Full-time, in our office in Gdańsk. No remote work.", "office"),
        ("Brak możliwości pracy zdalnej, praca w biurze", "office"),
        ("Warszawa", None),
        ("Darmowe lokale biurowe, owocowe czwartki", None),
        ("", None),
        (None, None),
    ],
)
def test_work_mode_from_text(text, expected):
    assert work_mode_from_text(text) == expected


def test_work_mode_from_jobposting():
    assert work_mode_from_jobposting({"jobLocationType": "TELECOMMUTE"}) == "remote"
    assert work_mode_from_jobposting({"jobLocationType": ["TELECOMMUTE"]}) == "remote"
    assert work_mode_from_jobposting({"jobLocation": {"address": "Berlin"}}) is None
    assert work_mode_from_jobposting(None) is None


def test_generic_parse_work_mode_reads_jsonld_then_text():
    page = (
        '<html><head><script type="application/ld+json">'
        '{"@type": "JobPosting", "title": "Dev", "jobLocationType": "TELECOMMUTE"}'
        "</script></head><body></body></html>"
    )
    assert generic.parse_work_mode(page) == "remote"
    text_page = "<html><body><main><p>" + "x " * 120 + "</p><p>Hybrid work in Berlin</p></main></body></html>"
    assert generic.parse_work_mode(text_page) == "hybrid"


def _skillshot_page(location: str, body: str = "<p>We need a dev</p>") -> str:
    return (
        "<html><body><nav>Praca zdalna - wszystkie oferty</nav><div id='job_presentation'><h1>Dev</h1>"
        "<p><span style='color: #777;'>dla</span> <b><a href='/users/7'>ACME</a> <img src='x.svg' /></b>"
        f" <span style='color: #777;'>w</span> {location}\n  </p>"
        f"<div>{body}</div></div></body></html>"
    )


def test_skillshot_parse_location():
    assert skillshot.parse_location(_skillshot_page("Warszawa / Zdalnie")) == "Warszawa / Zdalnie"
    assert skillshot.parse_location("<html><body><div id='job_presentation'><h1>Dev</h1></div></body></html>") == ""


@pytest.mark.parametrize(
    ("location", "body", "expected"),
    [
        ("Warszawa / Zdalnie", "", "remote"),
        ("remote", "", "remote"),
        ("Warszawa (model hybrydowy)", "", "hybrid"),
        ("Katowice / praca zdalna / system hybrydowy", "", "hybrid"),
        ("ON-SITE in Poznań", "", "office"),
        ("Łódź", "<ul><li>Pracy stacjonarnej w biurze</li></ul>", "office"),
        ("Gdańsk", "<p>Hybrid: 3 days in the office</p>", "hybrid"),
        ("Łódź", "<p>We need a dev</p>", "office"),
    ],
)
def test_skillshot_parse_work_mode(location, body, expected):
    assert skillshot.parse_work_mode(_skillshot_page(location, body)) == expected


def test_skillshot_parse_work_mode_ignores_page_chrome():
    """Page chrome ("Praca zdalna" in the nav) does not count; without a location there is no mode."""
    html = "<html><body><nav>Praca zdalna</nav><div id='job_presentation'><h1>Dev</h1></div></body></html>"
    assert skillshot.parse_work_mode(html) is None
