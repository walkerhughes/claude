"""Collapsing vintage columns, and joining first-printed against current."""

import pytest

from src import shaping

from ..fixtures.fred_api import VINTAGE_ROW

pytestmark = pytest.mark.unit


class TestVintageHistory:
    def test_repeated_vintages_collapse_to_the_actual_changes(self):
        # Six vintages, one real revision. The point of the tool: a vintage exists for
        # every publication of the series, not for every change to this observation.
        history = shaping.vintage_history(VINTAGE_ROW, "GDPC1")
        assert len(history) == 2
        assert history[0] == {"vintage": "2025-04-30", "value": 22900.0}
        assert history[1]["vintage"] == "2025-07-30"
        assert history[1]["value"] == 23000.0

    def test_a_real_revision_carries_its_size(self):
        history = shaping.vintage_history(VINTAGE_ROW, "GDPC1")
        assert history[1]["change"] == pytest.approx(100.0)
        assert history[1]["pct_change"] == pytest.approx(0.4367, abs=1e-3)

    def test_vintages_are_ordered_oldest_first_whatever_the_key_order(self):
        row = {"date": "2025-01-01", "X_20260101": "3", "X_20240101": "1", "X_20250101": "2"}
        assert [h["vintage"] for h in shaping.vintage_history(row, "X")] == [
            "2024-01-01",
            "2025-01-01",
            "2026-01-01",
        ]

    def test_a_never_revised_observation_has_one_entry(self):
        row = {"date": "2025-01-01", "X_20250201": "4.0", "X_20250301": "4.0"}
        history = shaping.vintage_history(row, "X")
        assert len(history) == 1
        assert "change" not in history[0]

    def test_the_date_column_is_not_mistaken_for_a_vintage(self):
        assert all(h["vintage"] != "date" for h in shaping.vintage_history(VINTAGE_ROW, "GDPC1"))

    def test_columns_for_another_series_are_ignored(self):
        row = {"date": "2025-01-01", "X_20250201": "1", "Y_20250201": "999"}
        assert [h["value"] for h in shaping.vintage_history(row, "X")] == [1.0]

    def test_a_malformed_column_name_is_skipped(self):
        row = {"date": "2025-01-01", "X_20250201": "1", "X_notadate": "999"}
        assert len(shaping.vintage_history(row, "X")) == 1

    def test_a_missing_value_does_not_produce_a_change(self):
        row = {"date": "2025-01-01", "X_20250201": ".", "X_20250301": "4.0"}
        history = shaping.vintage_history(row, "X")
        assert history[0]["value"] is None
        assert "change" not in history[1]

    def test_an_empty_row(self):
        assert shaping.vintage_history({"date": "2025-01-01"}, "X") == []


class TestRevisionRows:
    def test_joins_first_printed_against_current(self):
        rows = shaping.revision_rows(
            [("2025-01-01", 22900.0), ("2025-04-01", 23100.0)],
            [("2025-01-01", 23000.0), ("2025-04-01", 23100.0)],
        )
        assert rows[0] == {
            "date": "2025-01-01",
            "initial": 22900.0,
            "current": 23000.0,
            "revision": pytest.approx(100.0),
            "revision_pct": pytest.approx(0.4367, abs=1e-3),
        }

    def test_an_unrevised_observation_shows_a_zero_revision(self):
        rows = shaping.revision_rows([("2025-04-01", 23100.0)], [("2025-04-01", 23100.0)])
        assert rows[0]["revision"] == 0.0

    def test_rows_come_back_oldest_first(self):
        rows = shaping.revision_rows(
            [("2025-04-01", 1.0), ("2025-01-01", 2.0)],
            [("2025-04-01", 1.0), ("2025-01-01", 2.0)],
        )
        assert [r["date"] for r in rows] == ["2025-01-01", "2025-04-01"]

    def test_a_date_with_no_current_value_is_dropped(self):
        assert shaping.revision_rows([("2025-01-01", 1.0)], []) == []

    def test_a_downward_revision_is_negative(self):
        rows = shaping.revision_rows([("2025-01-01", 100.0)], [("2025-01-01", 90.0)])
        assert rows[0]["revision"] == pytest.approx(-10.0)
        assert rows[0]["revision_pct"] == pytest.approx(-10.0)

    def test_a_zero_initial_does_not_divide_by_zero(self):
        rows = shaping.revision_rows([("2025-01-01", 0.0)], [("2025-01-01", 5.0)])
        assert rows[0]["revision"] == 5.0
        assert "revision_pct" not in rows[0]
