"""get_observations, driven through the registered MCP server."""

import pytest

from ..fixtures.fred_api import DAILY_MAX, DAILY_MIN, DAILY_OBS

pytestmark = pytest.mark.integration


class TestSingleSeries:
    async def test_columnar_output(self, call):
        out = await call("get_observations", series_ids="UNRATE")
        assert out["dates"][:2] == ["2025-01-01", "2025-02-01"]
        assert out["values"]["UNRATE"][:2] == [4.0, 4.1]

    async def test_freds_missing_marker_becomes_null(self, call):
        out = await call("get_observations", series_ids="UNRATE")
        assert out["values"]["UNRATE"][2] is None  # "." in the fixture

    async def test_the_summary_skips_the_gap(self, call):
        summary = (await call("get_observations", series_ids="UNRATE"))["summary"]["UNRATE"]
        assert summary["latest"] == 4.3
        assert summary["latest_date"] == "2025-06-01"
        assert summary["count"] == 5
        assert summary["observations"] == 6
        assert (summary["min"], summary["max"]) == (4.0, 4.4)

    async def test_units_are_echoed_with_their_meaning(self, call):
        out = await call("get_observations", series_ids="UNRATE", units="yoy")
        assert out["units"] == "pc1"
        assert out["units_meaning"] == "percent change from a year ago"


class TestParametersSent:
    async def test_yoy_becomes_pc1_on_the_wire(self, call, fred):
        await call("get_observations", series_ids="UNRATE", units="year over year")
        assert fred.query("/series/observations")["units"] == "pc1"

    async def test_dates_are_normalized_before_the_request(self, call, fred):
        await call("get_observations", series_ids="UNRATE", start="2025", end="2025-06")
        params = fred.query("/series/observations")
        assert params["observation_start"] == "2025-01-01"
        assert params["observation_end"] == "2025-06-01"

    async def test_the_range_is_applied(self, call):
        out = await call("get_observations", series_ids="UNRATE", start="2025-04-01")
        assert out["dates"] == ["2025-04-01", "2025-05-01", "2025-06-01"]

    async def test_observations_come_back_oldest_first(self, call, fred):
        await call("get_observations", series_ids="UNRATE")
        assert fred.query("/series/observations")["sort_order"] == "asc"

    async def test_frequency_and_aggregation_are_echoed_only_when_set(self, call):
        plain = await call("get_observations", series_ids="UNRATE")
        assert "frequency" not in plain

        aggregated = await call(
            "get_observations", series_ids="UNRATE", frequency="quarterly", aggregation_method="total"
        )
        assert aggregated["frequency"] == "q"
        assert aggregated["aggregation_method"] == "sum"


class TestComparison:
    async def test_two_series_share_one_date_index(self, call):
        # The claim the tool exists for: comparison is one call, already aligned.
        out = await call("get_observations", series_ids="UNRATE,GDPC1")
        assert out["dates"] == [
            "2025-01-01",
            "2025-02-01",
            "2025-03-01",
            "2025-04-01",
            "2025-05-01",
            "2025-06-01",
        ]
        assert out["values"]["UNRATE"][0] == 4.0
        assert out["values"]["GDPC1"] == [23000.0, None, None, 23150.5, None, None]

    async def test_each_series_gets_its_own_summary(self, call):
        out = await call("get_observations", series_ids=["UNRATE", "GDPC1"])
        assert set(out["summary"]) == {"UNRATE", "GDPC1"}
        assert out["summary"]["GDPC1"]["latest"] == 23150.5

    async def test_one_series_is_fetched_per_id(self, call, fred):
        await call("get_observations", series_ids=["UNRATE", "GDPC1"])
        observation_calls = [p for p, _ in fred.requests if p.endswith("/series/observations")]
        assert len(observation_calls) == 2

    async def test_a_bad_id_does_not_take_down_the_good_one(self, call):
        out = await call("get_observations", series_ids=["UNRATE", "NOPE"])
        assert out["values"]["UNRATE"][0] == 4.0
        assert "does not exist" in out["errors"]["NOPE"]
        assert "NOPE" not in out["values"]


class TestDownsampling:
    async def test_a_long_series_is_thinned(self, call):
        out = await call("get_observations", series_ids="DGS10")
        assert out["points"]["total"] == len(DAILY_OBS)
        assert out["points"]["returned"] == 120
        assert out["points"]["dropped"] == len(DAILY_OBS) - 120
        assert len(out["dates"]) == 120

    async def test_the_summary_still_reports_the_true_extremes(self, call):
        # THE test for this tool. Both extremes sit in the interior of the fixture, so
        # a summary computed after thinning would miss them and quietly report the
        # sample's range as the series' range.
        summary = (await call("get_observations", series_ids="DGS10"))["summary"]["DGS10"]
        assert summary["min"] == DAILY_MIN
        assert summary["max"] == DAILY_MAX
        assert summary["count"] == len(DAILY_OBS)
        assert summary["observations"] == len(DAILY_OBS)

    async def test_the_first_and_last_dates_survive(self, call):
        out = await call("get_observations", series_ids="DGS10")
        assert out["dates"][0] == DAILY_OBS[0][0]
        assert out["dates"][-1] == DAILY_OBS[-1][0]

    async def test_thinning_is_stated_not_silent(self, call):
        out = await call("get_observations", series_ids="DGS10")
        assert "note" in out["points"]

    async def test_a_short_series_is_not_marked_as_thinned(self, call):
        out = await call("get_observations", series_ids="UNRATE")
        assert out["points"]["dropped"] == 0
        assert "note" not in out["points"]

    async def test_max_points_is_respected(self, call):
        out = await call("get_observations", series_ids="DGS10", max_points=10)
        assert out["points"]["returned"] == 10


class TestGuidedFailures:
    async def test_an_invented_unit_never_reaches_the_api(self, call, fred):
        out = await call("get_observations", series_ids="UNRATE", units="cagr")
        assert any("yoy" in s for s in out["suggestions"])
        assert not fred.requests

    async def test_an_unreadable_date_never_reaches_the_api(self, call, fred):
        out = await call("get_observations", series_ids="UNRATE", start="whenever")
        assert any("YYYY-MM-DD" in s for s in out["suggestions"])
        assert not fred.requests

    async def test_a_backwards_range_is_caught_locally(self, call, fred):
        out = await call("get_observations", series_ids="UNRATE", start="2025-01-01", end="2020-01-01")
        assert any("swap them" in s for s in out["suggestions"])
        assert not fred.requests
