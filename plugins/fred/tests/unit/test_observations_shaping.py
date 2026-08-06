"""Columnar alignment, summaries, and downsampling.

The assertion this file exists for: the summary is computed over every observation and
the point list is thinned afterwards, so a long series still reports its true extremes.
"""

import pytest

from src import shaping

pytestmark = pytest.mark.unit


class TestParseValue:
    @pytest.mark.parametrize("raw,expected", [("4.2", 4.2), ("0", 0.0), ("-1.5", -1.5), ("  4.2  ", 4.2)])
    def test_strings_become_floats(self, raw, expected):
        assert shaping.parse_value(raw) == expected

    @pytest.mark.parametrize("raw", [".", "", None, "n/a"])
    def test_freds_missing_marker_becomes_none(self, raw):
        # FRED writes a missing observation as "." and never as null.
        assert shaping.parse_value(raw) is None

    def test_zero_is_not_mistaken_for_missing(self):
        assert shaping.parse_value("0.0") == 0.0


class TestObservationPairs:
    def test_drops_the_realtime_padding(self):
        payload = {
            "observations": [
                {"realtime_start": "2026-08-05", "realtime_end": "2026-08-05", "date": "2025-01-01", "value": "4.0"},
                {"realtime_start": "2026-08-05", "realtime_end": "2026-08-05", "date": "2025-02-01", "value": "."},
            ]
        }
        assert shaping.observation_pairs(payload) == [("2025-01-01", 4.0), ("2025-02-01", None)]

    def test_an_empty_payload(self):
        assert shaping.observation_pairs({}) == []


class TestAlign:
    def test_one_series_is_its_own_index(self):
        dates, columns = shaping.align({"A": [("2025-01-01", 1.0), ("2025-02-01", 2.0)]})
        assert dates == ["2025-01-01", "2025-02-01"]
        assert columns == {"A": [1.0, 2.0]}

    def test_two_frequencies_union_with_nulls_in_the_gaps(self):
        # Monthly against quarterly. The gaps are null, not forward-filled: filling
        # them would invent observations that FRED never published.
        monthly = [("2025-01-01", 4.0), ("2025-02-01", 4.1), ("2025-03-01", 4.2)]
        quarterly = [("2025-01-01", 23000.0)]
        dates, columns = shaping.align({"M": monthly, "Q": quarterly})
        assert dates == ["2025-01-01", "2025-02-01", "2025-03-01"]
        assert columns["M"] == [4.0, 4.1, 4.2]
        assert columns["Q"] == [23000.0, None, None]

    def test_dates_present_only_in_the_second_series_still_appear(self):
        dates, columns = shaping.align({"A": [("2025-02-01", 1.0)], "B": [("2025-01-01", 2.0)]})
        assert dates == ["2025-01-01", "2025-02-01"]
        assert columns["A"] == [None, 1.0]
        assert columns["B"] == [2.0, None]

    def test_no_series(self):
        assert shaping.align({}) == ([], {})

    def test_every_column_is_the_length_of_the_index(self):
        dates, columns = shaping.align(
            {"A": [("2025-01-01", 1.0)], "B": [("2025-02-01", 2.0)], "C": [("2025-03-01", 3.0)]}
        )
        assert all(len(column) == len(dates) for column in columns.values())


class TestSummarize:
    def test_the_figures_a_question_actually_asks_for(self):
        pairs = [("2025-01-01", 4.0), ("2025-02-01", 4.1), ("2025-03-01", 4.4)]
        s = shaping.summarize(pairs)
        assert s["latest"] == 4.4
        assert s["latest_date"] == "2025-03-01"
        assert s["prior"] == 4.1
        assert s["change"] == pytest.approx(0.3)
        assert s["pct_change"] == pytest.approx(7.3171, abs=1e-3)
        assert (s["min"], s["max"]) == (4.0, 4.4)
        assert s["count"] == 3

    def test_missing_values_are_skipped_but_still_counted(self):
        pairs = [("2025-01-01", 4.0), ("2025-02-01", None), ("2025-03-01", 4.4)]
        s = shaping.summarize(pairs)
        assert s["count"] == 2  # observations with a value
        assert s["observations"] == 3  # rows FRED returned
        assert s["latest"] == 4.4
        assert s["prior"] == 4.0  # the null is skipped, not treated as the prior

    def test_latest_is_the_last_real_value_not_a_trailing_null(self):
        pairs = [("2025-01-01", 4.0), ("2025-02-01", 4.4), ("2025-03-01", None)]
        s = shaping.summarize(pairs)
        assert s["latest"] == 4.4
        assert s["latest_date"] == "2025-02-01"

    def test_a_single_observation_has_no_change(self):
        s = shaping.summarize([("2025-01-01", 4.0)])
        assert s["latest"] == 4.0
        assert "change" not in s and "prior" not in s

    def test_all_missing(self):
        assert shaping.summarize([("2025-01-01", None)]) == {"observations": 1, "count": 0}

    def test_empty(self):
        assert shaping.summarize([]) == {"observations": 0, "count": 0}

    def test_a_zero_prior_does_not_divide_by_zero(self):
        s = shaping.summarize([("2025-01-01", 0.0), ("2025-02-01", 2.0)])
        assert s["change"] == 2.0
        assert "pct_change" not in s

    def test_pct_change_is_signed_correctly_from_a_negative_prior(self):
        # Falling further below zero is a decrease, and dividing by a raw negative
        # would report it as an increase.
        s = shaping.summarize([("2025-01-01", -2.0), ("2025-02-01", -3.0)])
        assert s["change"] == -1.0
        assert s["pct_change"] == pytest.approx(-50.0)


class TestDownsample:
    def _series(self, n):
        dates = [f"2020-{i:04d}" for i in range(n)]
        return dates, {"A": [float(i) for i in range(n)]}

    def test_a_short_series_is_untouched(self):
        dates, columns = self._series(50)
        out_dates, out_columns, dropped = shaping.downsample(dates, columns, 120)
        assert (out_dates, out_columns, dropped) == (dates, columns, 0)

    def test_exactly_at_the_cap_is_untouched(self):
        dates, columns = self._series(120)
        assert shaping.downsample(dates, columns, 120)[2] == 0

    def test_thins_to_the_cap(self):
        dates, columns = self._series(5000)
        out_dates, out_columns, dropped = shaping.downsample(dates, columns, 120)
        assert len(out_dates) == 120
        assert len(out_columns["A"]) == 120
        assert dropped == 4880

    def test_the_first_and_last_points_always_survive(self):
        # Otherwise the series appears to start and end somewhere it does not.
        dates, columns = self._series(5000)
        out_dates, out_columns, _ = shaping.downsample(dates, columns, 120)
        assert out_dates[0] == dates[0]
        assert out_dates[-1] == dates[-1]
        assert out_columns["A"][0] == 0.0
        assert out_columns["A"][-1] == 4999.0

    def test_the_sample_is_evenly_spaced(self):
        dates, columns = self._series(1000)
        _, out_columns, _ = shaping.downsample(dates, columns, 100)
        gaps = {b - a for a, b in zip(out_columns["A"], out_columns["A"][1:])}
        assert max(gaps) - min(gaps) <= 1  # even to within rounding

    def test_every_column_stays_aligned_with_the_dates(self):
        dates, columns = self._series(1000)
        columns["B"] = [float(i) * 2 for i in range(1000)]
        out_dates, out_columns, _ = shaping.downsample(dates, columns, 50)
        assert all(len(column) == len(out_dates) for column in out_columns.values())
        assert all(b == a * 2 for a, b in zip(out_columns["A"], out_columns["B"]))

    def test_the_minimum_cap_still_produces_the_endpoints(self):
        dates, columns = self._series(1000)
        out_dates, _, dropped = shaping.downsample(dates, columns, 2)
        assert out_dates == [dates[0], dates[-1]]
        assert dropped == 998
