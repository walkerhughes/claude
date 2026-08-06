"""search_series and get_series, driven through the registered MCP server."""

import pytest

pytestmark = pytest.mark.integration


class TestSearchSeries:
    async def test_free_text_search_orders_by_popularity(self, call, fred):
        out = await call("search_series", query="unemployment")
        assert out["scope"] == "search"
        assert out["series"][0]["id"] == "UNRATE"
        params = fred.query("/series/search")
        assert params["search_text"] == "unemployment"
        assert params["order_by"] == "popularity"
        assert params["sort_order"] == "desc"

    async def test_the_key_is_sent_but_the_count_is_freds(self, call, fred):
        out = await call("search_series", query="unemployment")
        assert out["count"] == 4
        assert out["returned"] == len(out["series"])

    async def test_release_id_switches_endpoint_without_changing_the_shape(self, call, fred):
        out = await call("search_series", release_id=50)
        assert out["scope"] == "release"
        assert fred.query("/release/series")["release_id"] == "50"
        assert set(out) >= {"scope", "count", "returned", "series"}

    async def test_category_id_switches_endpoint(self, call, fred):
        out = await call("search_series", category_id=32447)
        assert out["scope"] == "category"
        assert fred.query("/category/series")["category_id"] == "32447"

    async def test_the_root_category_is_reachable(self, call, fred):
        await call("search_series", category_id=0)
        assert fred.query("/category/series")["category_id"] == "0"

    async def test_frequency_words_become_a_fred_tag(self, call, fred):
        await call("search_series", query="unemployment", frequency="monthly")
        assert fred.query("/series/search")["tag_names"] == "monthly"

    async def test_seasonal_shorthand_becomes_a_fred_tag(self, call, fred):
        out = await call("search_series", query="unemployment", seasonal_adjustment="NSA")
        assert fred.query("/series/search")["tag_names"] == "nsa"
        assert [s["id"] for s in out["series"]] == ["UNRATENSA"]

    async def test_both_filters_go_to_the_api_together(self, call, fred):
        # The reason this uses tag_names rather than filter_variable: FRED takes one
        # filter_variable per request, so the second would have to be applied locally
        # against a page FRED had already truncated, and count would stop being true.
        out = await call("search_series", query="unemployment", frequency="m", seasonal_adjustment="NSA", limit=2)
        params = fred.query("/series/search")
        assert params["tag_names"] == "monthly;nsa"
        assert int(params["limit"]) == 2  # no over-fetch: FRED did the filtering
        assert [s["id"] for s in out["series"]] == ["UNRATENSA"]
        assert out["count"] == 1  # the count describes exactly what was asked for
        assert out["filters"] == {"frequency": "m", "seasonal_adjustment": "nsa", "order_by": "popularity"}

    async def test_saar_resolves_to_the_tag_that_exists(self, call, fred):
        # FRED's seas tag group holds only sa and nsa; SAAR series carry sa.
        await call("search_series", query="gdp", seasonal_adjustment="SAAR")
        assert fred.query("/series/search")["tag_names"] == "sa"

    async def test_an_impossible_seasonal_adjustment_never_reaches_the_api(self, call, fred):
        out = await call("search_series", query="x", seasonal_adjustment="partially adjusted")
        assert "suggestions" in out
        assert not fred.requests

    async def test_notes_are_not_in_a_result_list(self, call):
        out = await call("search_series", query="unemployment")
        assert all("notes" not in s for s in out["series"])

    async def test_no_path_returns_guidance_not_a_traceback(self, call):
        out = await call("search_series")
        assert "did not pass validation" in out["error"]
        assert any("category_id" in s for s in out["suggestions"])

    async def test_an_impossible_frequency_never_reaches_the_api(self, call, fred):
        out = await call("search_series", query="x", frequency="hourly")
        assert "suggestions" in out
        assert not fred.requests


class TestGetSeries:
    async def test_metadata_by_default(self, call):
        out = await call("get_series", series_ids=["UNRATE"])
        series = out["series"][0]
        assert series["units"] == "Percent"
        assert series["seasonal_adjustment"] == "SA"
        assert "notes" not in series
        assert "release" not in series

    async def test_lowercase_ids_are_corrected(self, call, fred):
        out = await call("get_series", series_ids="unrate")
        assert out["series"][0]["id"] == "UNRATE"
        assert fred.query("/series")["series_id"] == "UNRATE"

    async def test_include_notes_adds_the_definition(self, call):
        out = await call("get_series", series_ids=["UNRATE"], include=["metadata", "notes"])
        assert "unemployed as a percentage" in out["series"][0]["notes"]

    async def test_include_all_fans_out_to_every_endpoint(self, call, fred):
        out = await call("get_series", series_ids=["UNRATE"], include=["all"])
        series = out["series"][0]
        assert series["release"] == {
            "id": 50,
            "name": "Employment Situation",
            "link": "http://www.bls.gov/ces/",
            "press_release": True,
        }
        assert series["categories"] == [{"id": 32447, "name": "Unemployment Rate"}]
        assert series["tags"] == ["headline figure", "monthly"]

    async def test_unrequested_endpoints_are_not_called(self, call, fred):
        await call("get_series", series_ids=["UNRATE"])
        paths = {path for path, _ in fred.requests}
        assert paths == {"/fred/series"}

    async def test_several_series_in_one_call(self, call):
        out = await call("get_series", series_ids="UNRATE,CPIAUCSL")
        assert [s["id"] for s in out["series"]] == ["UNRATE", "CPIAUCSL"]

    async def test_one_bad_id_does_not_take_down_the_good_ones(self, call):
        # FRED's "The series does not exist" never says which, so failing the whole
        # call would leave a model with three IDs and no idea which to fix.
        out = await call("get_series", series_ids=["UNRATE", "NOPE", "CPIAUCSL"])
        by_id = {s["id"]: s for s in out["series"]}
        assert by_id["UNRATE"]["units"] == "Percent"
        assert by_id["CPIAUCSL"]["units"] == "Index 1982-1984=100"
        assert "does not exist" in by_id["NOPE"]["error"]
        assert "search_series" in by_id["NOPE"]["suggestion"]

    async def test_an_unknown_include_is_guidance_not_a_failure(self, call):
        out = await call("get_series", series_ids=["UNRATE"], include=["observations"])
        assert any("include" in s for s in out["suggestions"])
