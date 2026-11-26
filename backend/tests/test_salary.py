import pytest

from app.tasks.scrape import generic
from app.tasks.scrape.salary import salary_from_jobposting, salary_from_text
from app.tasks.scrape.sources import skillshot


def _bounds(text, **kw):
    s = salary_from_text(text, **kw)
    return s and (s["min"], s["max"], s["currency"], s["period"], s["gross"])


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Wynagrodzenie: 15 000 - 20 000 PLN brutto/mies.", (15000, 20000, "PLN", "month", True)),
        ("B2B: 120-150 zł/h netto + VAT", (120, 150, "PLN", "hour", False)),
        ("Salary starting from 6,5k PLN (net)", (6500, None, "PLN", None, False)),
        ("Up to 90 000 EUR per year gross", (None, 90000, "EUR", "year", True)),
        ("Salary: 10-15k USD monthly", (10000, 15000, "USD", "month", None)),
        ("Stawka 12.000,00 zł", (12000, 12000, "PLN", None, None)),
        ("wynagrodzenie rzędu 6 000 na rękę", (6000, 6000, None, None, False)),
    ],
)
def test_salary_from_text(text, expected):
    assert _bounds(text) == expected


def test_salary_from_text_skips_non_salaries():
    assert salary_from_text("At least 2 years of experience\n.NET 8, 100% remote") is None
    assert salary_from_text("") is None


def test_salary_from_text_prefers_salary_line_and_keeps_raw():
    s = salary_from_text("Benefits worth 500 PLN\nWe pay 20 000 PLN gross")
    assert (s["min"], s["raw"]) == (20000, "We pay 20 000 PLN gross")


def test_dotnet_is_not_net_salary():
    assert salary_from_text(".NET developer, salary 20 000 PLN")["gross"] is None


def test_default_currency():
    assert salary_from_text("wynagrodzenie 8 000", default_currency="PLN")["currency"] == "PLN"


def test_salary_from_jobposting():
    ld = {"baseSalary": {"currency": "pln", "value": {"minValue": 100, "maxValue": 140, "unitText": "HOUR"}}}
    s = salary_from_jobposting(ld)
    assert (s["min"], s["max"], s["currency"], s["period"]) == (100, 140, "PLN", "hour")
    assert salary_from_jobposting({}) is None


def test_generic_parse_salary_reads_jsonld_then_text():
    page = (
        '<html><script type="application/ld+json">{"@type": "JobPosting", "title": "Dev", '
        '"baseSalary": {"currency": "EUR", "value": {"value": 5000, "unitText": "MONTH"}}}</script></html>'
    )
    assert generic.parse_salary(page)["max"] == 5000
    text_page = "<html><body><main><p>" + "x " * 120 + "</p><p>Salary: 7 000 PLN</p></main></body></html>"
    assert generic.parse_salary(text_page)["min"] == 7000


def test_skillshot_parse_salary():
    html = (
        "<html><body><nav>Premium 99 zł</nav><div id='job_presentation'><h1>Dev</h1>"
        "<ul><li>Employment contract</li><li>wynagrodzenie na okresie próbnym rzędu 6 000 na rękę</li></ul>"
        "</div></body></html>"
    )
    s = skillshot.parse_salary(html)
    assert (s["min"], s["max"], s["currency"], s["gross"]) == (6000, 6000, "PLN", False)
    assert skillshot.parse_salary("<html><body><div id='job_presentation'>No pay info</div></body></html>") is None
