"""Trimming: what survives, what is dropped, and why."""

import pytest

from src import shaping

from ..fixtures.fred_api import CPIAUCSL, UNRATE

pytestmark = pytest.mark.unit


class TestTrimSeries:
    def test_keeps_what_decides_whether_a_number_means_what_you_think(self):
        out = shaping.trim_series(UNRATE)
        assert out["id"] == "UNRATE"
        assert out["units"] == "Percent"
        assert out["frequency"] == "Monthly"
        assert out["seasonal_adjustment"] == "SA"
        assert out["observation_end"] == "2026-06-01"
        assert out["last_updated"].startswith("2026-07-02")

    def test_drops_the_fields_that_repeat_or_duplicate(self):
        out = shaping.trim_series(UNRATE)
        for dropped in ("realtime_start", "realtime_end", "frequency_short", "units_short", "group_popularity"):
            assert dropped not in out

    def test_notes_are_opt_in(self):
        assert "notes" not in shaping.trim_series(UNRATE)
        assert "notes" in shaping.trim_series(UNRATE, notes=True)

    def test_notes_whitespace_is_collapsed(self):
        # FRED notes carry \r\n\r\n paragraph breaks that cost tokens and read no better.
        out = shaping.trim_series(UNRATE, notes=True)
        assert "\r" not in out["notes"] and "\n" not in out["notes"]
        assert "unemployed as a percentage of the labor force" in out["notes"]

    def test_a_sparse_series_object_does_not_invent_keys(self):
        assert shaping.trim_series({"id": "X"}) == {"id": "X"}

    def test_trimming_is_most_of_the_payload(self):
        # The claim the design rests on, asserted rather than asserted-in-prose.
        before = len(str(UNRATE))
        after = len(str(shaping.trim_series(UNRATE)))
        assert after < before * 0.5


class TestSeriesList:
    def test_reads_freds_misspelled_key(self):
        out = shaping.series_list({"seriess": [UNRATE, CPIAUCSL]})
        assert [s["id"] for s in out] == ["UNRATE", "CPIAUCSL"]

    def test_an_empty_payload_is_an_empty_list(self):
        assert shaping.series_list({}) == []


class TestOtherTrims:
    def test_release(self):
        raw = {"id": 50, "name": "Employment Situation", "link": "http://x", "press_release": True, "realtime_start": "x"}  # noqa: E501
        assert shaping.trim_release(raw) == {
            "id": 50,
            "name": "Employment Situation",
            "link": "http://x",
            "press_release": True,
        }

    def test_category_keeps_id_and_name_only(self):
        raw = {"id": 32447, "name": "Unemployment Rate", "parent_id": 12, "notes": "long prose"}
        assert shaping.trim_category(raw) == {"id": 32447, "name": "Unemployment Rate"}

    def test_tags_become_names(self):
        raw = [{"name": "monthly", "group_id": "freq", "popularity": 93}, {"name": "usa"}]
        assert shaping.tag_names(raw) == ["monthly", "usa"]

    def test_first_or_empty(self):
        assert shaping.first_or_empty({"seriess": [UNRATE]}, "seriess")["id"] == "UNRATE"
        assert shaping.first_or_empty({"seriess": []}, "seriess") == {}
        assert shaping.first_or_empty({}, "seriess") == {}
