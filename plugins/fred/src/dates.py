"""Date parsing for arguments FRED will only accept as YYYY-MM-DD.

A model asked for "the last five years" writes ``start="5y"`` or ``start="2020"`` or
``start="last 5 years"``. FRED answers all three with HTTP 400 and a message about a
variable name. Since none of these are ambiguous, they are translated rather than
rejected.
"""

import re
from datetime import date

# "5y", "5 years", "last 5 years", "past 18 months", "10yr".
_RELATIVE = re.compile(
    r"^(?:last|past)?\s*(\d+)\s*(d|w|m|q|y|yr|day|days|week|weeks|month|months|quarter|quarters|year|years)$"
)

_UNIT_MONTHS = {"m": 1, "mo": 1, "month": 1, "months": 1, "q": 3, "quarter": 3, "quarters": 3}
_UNIT_YEARS = {"y": 1, "yr": 1, "year": 1, "years": 1}
_UNIT_DAYS = {"d": 1, "day": 1, "days": 1, "w": 7, "week": 7, "weeks": 7}


def today() -> date:
    """Indirection so tests can pin the clock without patching the stdlib."""
    return date.today()


def days_before(day: date, count: int) -> date:
    return date.fromordinal(day.toordinal() - count)


def days_after(day: date, count: int) -> date:
    return date.fromordinal(day.toordinal() + count)


def parse(value: str, *, field: str) -> str:
    """Return a YYYY-MM-DD string, or "" for an unset value.

    Accepted, beyond a full date: a bare year ("2020"), a year-month ("2020-01"),
    "today"/"now", "ytd", and a relative span ("5y", "18 months", "last 10 years")
    measured back from today.
    """
    text = " ".join(str(value).strip().lower().split())
    if not text:
        return ""

    if text in ("today", "now"):
        return today().isoformat()
    if text in ("ytd", "year to date", "this year"):
        return today().replace(month=1, day=1).isoformat()

    if re.fullmatch(r"\d{4}", text):
        return f"{text}-01-01"
    if re.fullmatch(r"\d{4}-\d{2}", text):
        return f"{text}-01"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        # Round-tripped through date() so 2020-13-01 is caught here rather than by FRED.
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError as exc:
            raise ValueError(f"{field}={value!r} is not a real date: {exc}") from exc

    match = _RELATIVE.match(text)
    if match:
        amount, unit = int(match.group(1)), match.group(2)
        return _ago(amount, unit).isoformat()

    raise ValueError(
        f"{field}={value!r} could not be read as a date. Use YYYY-MM-DD, a year "
        '("2020"), a year-month ("2020-01"), a span back from today ("5y", '
        '"18 months"), "ytd", or "today".'
    )


def _ago(amount: int, unit: str) -> date:
    """Today, minus ``amount`` of ``unit``. Calendar arithmetic, no dependency."""
    now = today()
    if unit in _UNIT_DAYS:
        return date.fromordinal(max(1, now.toordinal() - amount * _UNIT_DAYS[unit]))
    if unit in _UNIT_YEARS:
        months = amount * 12
    else:
        months = amount * _UNIT_MONTHS[unit]

    total = now.year * 12 + (now.month - 1) - months
    year, month = divmod(total, 12)
    month += 1
    # Clamp the day: three months before the 31st is not the 31st of a 30-day month.
    day = min(now.day, _days_in_month(year, month))
    return date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year + (month == 12), month % 12 + 1, 1).toordinal()) - date(year, month, 1).toordinal()
