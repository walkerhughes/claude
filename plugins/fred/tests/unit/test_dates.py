"""Relative and partial dates become the YYYY-MM-DD that FRED will accept."""

from datetime import date

import pytest

from src import dates

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _pinned_clock(monkeypatch):
    # Mid-month and mid-year, so the month and year arithmetic is actually exercised
    # rather than passing by luck on the 1st of January.
    monkeypatch.setattr(dates, "today", lambda: date(2026, 8, 5))


class TestExplicitDates:
    @pytest.mark.parametrize(
        "written,expected",
        [
            ("2020-01-15", "2020-01-15"),
            ("2020", "2020-01-01"),
            ("2020-03", "2020-03-01"),
            ("  2020-01-15  ", "2020-01-15"),
            ("", ""),
            ("   ", ""),
        ],
    )
    def test_forms(self, written, expected):
        assert dates.parse(written, field="start") == expected

    def test_an_impossible_date_is_caught_here_not_by_fred(self):
        with pytest.raises(ValueError, match="not a real date"):
            dates.parse("2020-13-01", field="start")

    def test_february_30_is_rejected(self):
        with pytest.raises(ValueError, match="not a real date"):
            dates.parse("2021-02-30", field="start")


class TestRelativeDates:
    @pytest.mark.parametrize(
        "written,expected",
        [
            ("today", "2026-08-05"),
            ("now", "2026-08-05"),
            ("ytd", "2026-01-01"),
            ("year to date", "2026-01-01"),
            ("5y", "2021-08-05"),
            ("5 years", "2021-08-05"),
            ("last 5 years", "2021-08-05"),
            ("past 5 years", "2021-08-05"),
            ("10yr", "2016-08-05"),
            ("6m", "2026-02-05"),
            ("18 months", "2025-02-05"),
            ("2 quarters", "2026-02-05"),
            ("30d", "2026-07-06"),
            ("2 weeks", "2026-07-22"),
        ],
    )
    def test_spans_back_from_today(self, written, expected):
        assert dates.parse(written, field="start") == expected

    def test_case_and_spacing_are_forgiven(self):
        assert dates.parse("Last 5 Years", field="start") == "2021-08-05"

    def test_a_month_shift_onto_a_shorter_month_clamps(self, monkeypatch):
        # 3 months before the 31st of May is the 28th of February, not the 31st.
        monkeypatch.setattr(dates, "today", lambda: date(2026, 5, 31))
        assert dates.parse("3m", field="start") == "2026-02-28"

    def test_a_year_shift_across_a_leap_day_clamps(self, monkeypatch):
        monkeypatch.setattr(dates, "today", lambda: date(2024, 2, 29))
        assert dates.parse("1y", field="start") == "2023-02-28"

    def test_a_span_crossing_the_year_boundary(self, monkeypatch):
        monkeypatch.setattr(dates, "today", lambda: date(2026, 2, 10))
        assert dates.parse("6m", field="start") == "2025-08-10"


class TestFailure:
    def test_nonsense_names_the_field_and_lists_the_forms(self):
        with pytest.raises(ValueError) as exc:
            dates.parse("whenever", field="end")
        message = str(exc.value)
        assert "end='whenever'" in message
        assert "YYYY-MM-DD" in message
        assert "ytd" in message
