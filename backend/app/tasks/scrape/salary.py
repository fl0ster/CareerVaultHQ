"""Best-effort salary extraction shared by every scraper source.

A parsed salary is a plain dict (stored as JSON in ``job_parse_results.salary``)::

    {
        "min": 15000.0,        # lower bound (None when only "up to X" is stated)
        "max": 20000.0,        # upper bound (None when only "from X" is stated)
        "currency": "PLN",     # ISO code, None when unknown
        "period": "month",     # hour | day | month | year, None when unknown
        "gross": True,         # True brutto/gross, False netto/net, None when unstated
        "raw": "15 000 - 20 000 PLN brutto",  # the text the salary was read from
    }

``salary_from_text`` scans plain text (a job description) line by line,
``salary_from_jobposting`` reads a schema.org ``JobPosting.baseSalary``. Source modules
may define a ``parse_salary(html) -> dict | None`` hook built on these; the parse task falls
back to ``salary_from_text(description)`` for sources that do not.
"""

from __future__ import annotations

import re
from typing import Any

MAX_RAW_CHARS = 200

_CURRENCIES = (
    (re.compile(r"(?i)(?<![a-z])(pln|zł|zl|złotych)(?![a-z])"), "PLN"),
    (re.compile(r"(?i)(€|(?<![a-z])eur(o)?(?![a-z]))"), "EUR"),
    (re.compile(r"(?i)(\$|(?<![a-z])usd(?![a-z]))"), "USD"),
    (re.compile(r"(?i)(£|(?<![a-z])gbp(?![a-z]))"), "GBP"),
    (re.compile(r"(?i)(?<![a-z])chf(?![a-z])"), "CHF"),
)
_KEYWORDS = re.compile(
    r"(?i)(wynagrodz|salary|\bpay\b|compensation|stawk|pensj|zarobk|zarabia|widełki|widelki|\brate\b|remuneration)"
)
_PERIODS = (
    (re.compile(r"(?i)(/\s*h\b|/\s*godz|per hour|hourly|an hour|na godzin|za godzin|godzinow|\bh/)"), "hour"),
    (re.compile(r"(?i)(/\s*d(ay|zień)\b|per day|daily|dziennie|za dzień|dniówk|\bmd\b|man-?day)"), "day"),
    (re.compile(r"(?i)(/\s*(rok|year|yr)\b|per year|annual|yearly|rocznie|na rok|\bp\.a\.)"), "year"),
    (re.compile(r"(?i)(/\s*(mies|m-c|mc|month|mo)\b|per month|monthly|miesięczn|miesiecz|na miesiąc|mies\.)"), "month"),
)
_GROSS = re.compile(r"(?i)(brutto|gross)")
_NET = re.compile(r"(?i)(netto|(?<![.\w])net\b|na rękę|na reke|\+\s*vat)")

_AMOUNT = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:[  .,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d+)?)"
    r"\s*(k\b|tys\.?|tyś\.?|thousand)?(?!\s*%)",
    re.I,
)
_RANGE_GAP = re.compile(r"^\s*(-|–|—|do|to|until)\s*$", re.I)
_FROM = re.compile(r"(?i)(\bod|\bfrom|starting|min\.?|minimum|at least|\bpowyżej)\s*$")
_UP_TO = re.compile(r"(?i)(\bdo|up to|\bmax\.?|maximum|\bto)\s*$")


def _to_number(digits: str, suffix: str | None) -> float:
    if re.fullmatch(r"\d{1,3}(?:[  .,]\d{3})+(?:[.,]\d{1,2})?", digits):
        # "12 000", "12.000,50", "6,500" -> thousands groups (+ optional decimals)
        m = re.fullmatch(r"(.*?)(?:[.,](\d{1,2}))?", digits)
        whole, frac = m.group(1), m.group(2)
        number = float(re.sub(r"[  .,]", "", whole) + (f".{frac}" if frac else ""))
    else:
        number = float(digits.replace(",", "."))
    return number * 1000 if suffix else number


def _amounts(line: str) -> list[tuple[float, int, int, bool]]:
    """``(value, start, end, has_k_suffix)`` of every amount in ``line``."""
    return [(_to_number(m.group(1), m.group(2)), m.start(), m.end(), bool(m.group(2))) for m in _AMOUNT.finditer(line)]


def _currency(text: str) -> str | None:
    for pattern, code in _CURRENCIES:
        if pattern.search(text):
            return code
    return None


def _period(text: str) -> str | None:
    for pattern, period in _PERIODS:
        if pattern.search(text):
            return period
    return None


def _gross(text: str) -> bool | None:
    if _GROSS.search(text):
        return True
    if _NET.search(text):
        return False
    return None


def _salary_from_line(line: str, default_currency: str | None) -> dict[str, Any] | None:
    currency = _currency(line)
    keyword = bool(_KEYWORDS.search(line))
    if not currency and not keyword:
        return None
    amounts = _amounts(line)
    if not amounts:
        return None
    # Without a currency only clearly salary-sized numbers count ("2 years" is not a salary).
    minimum = 10 if currency else 1000
    for i, (value, start, end, k) in enumerate(amounts):
        lo = hi = value
        nxt = amounts[i + 1] if i + 1 < len(amounts) else None
        if nxt and _RANGE_GAP.match(line[end : nxt[1]]):
            hi = nxt[0]
            if nxt[3] and not k and lo < 1000:  # "10-15k"
                lo *= 1000
        if hi < minimum or lo < minimum:
            continue
        if lo > hi:
            lo, hi = hi, lo
        before = line[:start]
        if lo == hi:
            if _FROM.search(before):
                hi = None
            elif _UP_TO.search(before):
                lo = None
        return {
            "min": lo,
            "max": hi,
            "currency": currency or default_currency,
            "period": _period(line[start:]) or _period(line),
            "gross": _gross(line),
            "raw": line[:MAX_RAW_CHARS],
        }
    return None


def salary_from_text(text: str | None, default_currency: str | None = None) -> dict[str, Any] | None:
    """The first salary stated in ``text`` (lines mentioning both a currency and a salary
    keyword win over lines with just one of them); ``None`` when none is found."""
    if not text:
        return None
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    ranked = sorted(
        range(len(lines)),
        key=lambda i: (not (_currency(lines[i]) and _KEYWORDS.search(lines[i])), not _currency(lines[i]), i),
    )
    for i in ranked:
        salary = _salary_from_line(lines[i], default_currency)
        if salary:
            return salary
    return None


_UNIT_PERIODS = {"HOUR": "hour", "DAY": "day", "WEEK": "week", "MONTH": "month", "YEAR": "year"}


def _float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def salary_from_jobposting(ld: dict | None) -> dict[str, Any] | None:
    """The ``baseSalary`` of a schema.org ``JobPosting``; ``None`` when absent."""
    sal = (ld or {}).get("baseSalary")
    if isinstance(sal, list):
        sal = next((s for s in sal if isinstance(s, dict)), None)
    if not isinstance(sal, dict):
        return None
    value = sal.get("value")
    unit = ""
    if isinstance(value, dict):
        unit = str(value.get("unitText") or "")
        lo, hi = _float(value.get("minValue")), _float(value.get("maxValue"))
        if lo is None and hi is None:
            lo = hi = _float(value.get("value"))
    else:
        lo = hi = _float(value)
    if lo is None and hi is None:
        return None
    currency = sal.get("currency") or (value.get("currency") if isinstance(value, dict) else None)
    return {
        "min": lo,
        "max": hi,
        "currency": str(currency).upper() if currency else None,
        "period": _UNIT_PERIODS.get(unit.upper()),
        "gross": None,
        "raw": f"{lo or ''}-{hi or ''} {currency or ''} {unit}".strip()[:MAX_RAW_CHARS],
    }
