"""Correction, then validation.

These are the misuse tests: each case is a request a model plausibly writes, and the
assertion is that it either becomes the right FRED call or fails with a message naming
the fix.
"""

import pytest
from pydantic import ValidationError

from src.schemas import GetSeriesArgs, SearchArgs, normalize_series_ids

pytestmark = pytest.mark.unit


class TestSeriesIdCorrection:
    @pytest.mark.parametrize(
        "written,expected",
        [
            ("unrate", ["UNRATE"]),
            ("UNRATE", ["UNRATE"]),
            ("UNRATE,CPIAUCSL", ["UNRATE", "CPIAUCSL"]),
            ("UNRATE, CPIAUCSL", ["UNRATE", "CPIAUCSL"]),
            ("UNRATE CPIAUCSL", ["UNRATE", "CPIAUCSL"]),
            (["unrate", "cpiaucsl"], ["UNRATE", "CPIAUCSL"]),
            (["UNRATE,CPIAUCSL"], ["UNRATE", "CPIAUCSL"]),
            ("  unrate  ", ["UNRATE"]),
        ],
    )
    def test_the_shapes_a_model_writes(self, written, expected):
        assert GetSeriesArgs(series_ids=written).series_ids == expected

    def test_duplicates_are_dropped_and_order_kept(self):
        assert normalize_series_ids(["GDPC1", "unrate", "GDPC1"]) == ["GDPC1", "UNRATE"]

    def test_a_wrong_type_reaches_pydantic_as_a_type_error(self):
        with pytest.raises(ValidationError):
            GetSeriesArgs(series_ids=[123])

    def test_empty_is_rejected(self):
        with pytest.raises(ValidationError):
            GetSeriesArgs(series_ids=[])

    def test_the_fan_out_is_bounded(self):
        with pytest.raises(ValidationError):
            GetSeriesArgs(series_ids=[f"S{i}" for i in range(21)])


class TestInclude:
    def test_defaults_to_metadata(self):
        assert GetSeriesArgs(series_ids="UNRATE").include == ["metadata"]

    def test_a_bare_string_becomes_a_list(self):
        assert GetSeriesArgs(series_ids="UNRATE", include="notes").include == ["notes"]

    def test_comma_joined(self):
        assert GetSeriesArgs(series_ids="UNRATE", include="notes,tags").include == ["notes", "tags"]

    def test_all_expands(self):
        args = GetSeriesArgs(series_ids="UNRATE", include=["all"])
        assert set(args.include) == {"metadata", "notes", "release", "categories", "tags"}

    def test_case_is_forgiven(self):
        assert GetSeriesArgs(series_ids="UNRATE", include=["Notes"]).include == ["notes"]

    def test_unknown_include_names_the_valid_ones(self):
        with pytest.raises(ValidationError, match="observations"):
            GetSeriesArgs(series_ids="UNRATE", include=["observations"])


class TestFrequencyCorrection:
    @pytest.mark.parametrize(
        "written,expected",
        [
            ("monthly", "m"),
            ("Monthly", "m"),
            ("month", "m"),
            ("M", "m"),
            ("quarterly", "q"),
            ("annual", "a"),
            ("yearly", "a"),
            ("daily", "d"),
            ("weekly", "w"),
            ("bi-weekly", "bw"),
            ("semiannual", "sa"),
            ("", ""),
        ],
    )
    def test_words_become_codes(self, written, expected):
        assert SearchArgs(query="x", frequency=written).frequency == expected

    def test_a_frequency_fred_does_not_have_is_rejected_locally(self):
        with pytest.raises(ValidationError, match="unknown frequency"):
            SearchArgs(query="x", frequency="hourly")


class TestSeasonalCorrection:
    @pytest.mark.parametrize(
        "written,expected",
        [
            ("SA", "sa"),
            ("sa", "sa"),
            ("seasonally adjusted", "sa"),
            ("adjusted", "sa"),
            ("NSA", "nsa"),
            ("not seasonally adjusted", "nsa"),
            ("unadjusted", "nsa"),
            # FRED's seas tag group holds only sa and nsa; SAAR series carry sa.
            ("saar", "sa"),
        ],
    )
    def test_shorthand_becomes_the_tag_fred_filters_on(self, written, expected):
        assert SearchArgs(query="x", seasonal_adjustment=written).seasonal_adjustment == expected

    def test_an_adjustment_fred_does_not_have_is_rejected_locally(self):
        with pytest.raises(ValidationError, match="unknown seasonal_adjustment"):
            SearchArgs(query="x", seasonal_adjustment="partially adjusted")


class TestTagNames:
    def test_both_filters_join_into_one_tag_list(self):
        args = SearchArgs(query="x", frequency="monthly", seasonal_adjustment="NSA")
        assert args.tag_names == "monthly;nsa"

    def test_frequency_alone(self):
        assert SearchArgs(query="x", frequency="q").tag_names == "quarterly"

    def test_the_semiannual_code_is_not_confused_with_the_sa_tag(self):
        # frequency="sa" means semiannual; seasonal_adjustment="sa" means adjusted.
        # They share a spelling and must not resolve to the same tag.
        assert SearchArgs(query="x", frequency="sa").tag_names == "semiannual"
        assert SearchArgs(query="x", seasonal_adjustment="sa").tag_names == "sa"

    def test_no_filters_means_no_tag_parameter(self):
        assert SearchArgs(query="x").tag_names == ""


class TestSearchPaths:
    def test_query_routes_to_search(self):
        assert SearchArgs(query="cpi").path == "/series/search"

    def test_release_id_routes_to_release_series(self):
        assert SearchArgs(release_id=50).path == "/release/series"

    def test_category_id_routes_to_category_series(self):
        assert SearchArgs(category_id=32447).path == "/category/series"

    def test_the_root_category_is_not_mistaken_for_unset(self):
        # category_id=0 is the FRED root, so a falsy check here would break browsing.
        assert SearchArgs(category_id=0).path == "/category/series"

    def test_no_path_at_all_says_which_three_to_choose_from(self):
        with pytest.raises(ValidationError, match="category_id"):
            SearchArgs()

    def test_a_blank_query_is_not_a_path(self):
        with pytest.raises(ValidationError):
            SearchArgs(query="   ")

    def test_two_paths_at_once_is_rejected(self):
        with pytest.raises(ValidationError, match="only one of"):
            SearchArgs(query="cpi", release_id=50)


class TestSearchLimits:
    def test_order_by_is_corrected_and_checked(self):
        assert SearchArgs(query="x", order_by="Group Popularity").order_by == "group_popularity"
        with pytest.raises(ValidationError, match="unknown order_by"):
            SearchArgs(query="x", order_by="relevance")

    @pytest.mark.parametrize("limit", [0, 101])
    def test_limit_is_bounded(self, limit):
        with pytest.raises(ValidationError):
            SearchArgs(query="x", limit=limit)
