"""get_revisions and get_release_calendar, through the registered MCP server."""

from datetime import date, timedelta

import pytest

from src import dates as dates_module

from ..fixtures.fred_api import FIXED_TODAY, NEXT_RELEASE_50_OFFSET, RELEASE_OFFSETS, TODAY


def day(offset: int) -> str:
    """A fixture release date, as the calendar will report it."""
    return (FIXED_TODAY + timedelta(days=offset)).isoformat()

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _pinned_clock(monkeypatch):
    """Pin today to the fixture's, so the released/upcoming split is deterministic."""
    monkeypatch.setattr(dates_module, "today", lambda: date.fromisoformat(TODAY))


class TestRevisionsForOneDate:
    async def test_the_real_time_window_is_always_set(self, call, fred):
        # The bug this tool exists to prevent. Without it FRED answers with "No vintage
        # dates exist for the specified real-time period", which reads like the series
        # has no revision history rather than like a missing parameter.
        await call("get_revisions", series_id="GDPC1", observation_date="2025-01-01")
        params = fred.query("/series/observations")
        assert params["realtime_start"] == "1776-07-04"
        assert params["realtime_end"] == "9999-12-31"

    async def test_output_type_2_is_requested(self, call, fred):
        await call("get_revisions", series_id="GDPC1", observation_date="2025-01-01")
        assert fred.query("/series/observations")["output_type"] == "2"

    async def test_six_vintages_become_two_entries(self, call):
        out = await call("get_revisions", series_id="GDPC1", observation_date="2025-01-01")
        assert len(out["revisions"]) == 2
        assert out["revision_count"] == 1
        assert out["initial"]["value"] == 22900.0
        assert out["current"]["value"] == 23000.0

    async def test_the_date_is_normalized_first(self, call, fred):
        await call("get_revisions", series_id="gdpc1", observation_date="2025-01")
        params = fred.query("/series/observations")
        assert params["series_id"] == "GDPC1"
        assert params["observation_start"] == "2025-01-01"
        assert params["observation_end"] == "2025-01-01"

    async def test_a_date_with_no_observation_explains_itself(self, call):
        out = await call("get_revisions", series_id="GDPC1", observation_date="2025-02-15")
        assert out["revisions"] == []
        assert "frequency" in out["note"]


class TestRevisionOverview:
    async def test_initial_against_current(self, call):
        out = await call("get_revisions", series_id="GDPC1")
        by_date = {row["date"]: row for row in out["observations"]}
        assert by_date["2025-01-01"]["initial"] == 22900.0
        assert by_date["2025-01-01"]["current"] == 23000.0
        assert by_date["2025-01-01"]["revision"] == pytest.approx(100.0)

    async def test_an_unrevised_observation_is_not_counted_as_revised(self, call):
        out = await call("get_revisions", series_id="GDPC1")
        assert out["observations"][1]["revision"] == 0.0
        assert out["revised"] == 1

    async def test_the_initial_request_uses_output_type_4_and_the_window(self, call, fred):
        await call("get_revisions", series_id="GDPC1")
        initial = next(
            params
            for path, params in fred.requests
            if path.endswith("/series/observations") and params.get("output_type") == "4"
        )
        assert initial["realtime_start"] == "1776-07-04"

    async def test_vintage_context_comes_back(self, call):
        out = await call("get_revisions", series_id="GDPC1")
        assert out["vintages"] == {"count": 6, "latest": "2025-09-25"}

    async def test_a_series_that_is_never_revised(self, call):
        out = await call("get_revisions", series_id="UNRATE")
        assert out["revised"] == 0
        # UNRATE's fixture carries a missing observation, which has no revision to
        # report at all. That is different from a revision of zero, and the absent
        # key is the honest way to say so.
        assert all(row.get("revision") in (0.0, None) for row in out["observations"])
        assert any("revision" not in row for row in out["observations"])

    async def test_a_bad_series_is_guidance_not_a_traceback(self, call):
        out = await call("get_revisions", series_id="NOPE")
        assert "does not exist" in out["error"]
        assert any("search_series" in s for s in out["suggestions"])

    async def test_a_blank_series_id_never_reaches_the_api(self, call, fred):
        out = await call("get_revisions", series_id="")
        assert any("required" in s for s in out["suggestions"])
        assert not fred.requests


class TestReleaseCalendar:
    async def test_splits_on_today(self, call):
        out = await call("get_release_calendar")
        assert out["today"] == TODAY
        # Offsets, not literals: the fixture generates release dates relative to the
        # clock, so a hard-coded date would only be right for one day.
        assert [r["date"] for r in out["released"]] == [day(-5), day(-2), day(0)]
        assert [r["date"] for r in out["upcoming"]] == [day(9), day(12)]

    async def test_a_release_dated_today_counts_as_released(self, call):
        # It has come out; a model asking "what came out today" should see it.
        out = await call("get_release_calendar")
        assert TODAY in [r["date"] for r in out["released"]]

    async def test_the_default_window_straddles_today(self, call):
        out = await call("get_release_calendar")
        assert out["window"] == {"start": "2026-07-29", "end": "2026-08-19"}

    async def test_future_dates_are_asked_for_when_the_window_reaches_forward(self, call, fred):
        # Without the flag FRED returns only dates that already produced data, so the
        # whole "what is next" half of the question comes back empty.
        await call("get_release_calendar")
        assert fred.query("/releases/dates")["include_release_dates_with_no_data"] == "true"

    async def test_a_purely_historical_window_does_not_set_the_flag(self, call, fred):
        out = await call("get_release_calendar", start="2026-07-01", end="2026-08-01")
        assert "include_release_dates_with_no_data" not in fred.query("/releases/dates")
        assert out["upcoming"] == []
        # And it does not spend a request asking about a future it was not asked about.
        assert len([p for p, _ in fred.requests if p.endswith("/releases/dates")]) == 1

    async def test_each_half_is_fetched_with_its_own_limit(self, call, fred):
        # One request across the whole window is truncated by limit before the split,
        # and FRED returns dates ascending, so the truncation lands entirely on the
        # future: "50 released, 0 upcoming" for a window full of scheduled releases.
        await call("get_release_calendar", limit=1)
        windows = [
            (params["realtime_start"], params["realtime_end"])
            for path, params in fred.requests
            if path.endswith("/releases/dates")
        ]
        assert windows == [("2026-07-29", TODAY), ("2026-08-06", "2026-08-19")]

    async def test_a_limited_page_says_how_much_it_left_out(self, call):
        out = await call("get_release_calendar", limit=1)
        assert len(out["released"]) == 1
        assert len(out["upcoming"]) == 1
        assert out["totals"] == {"released": 3, "upcoming": 2}

    async def test_the_next_release_for_one_publication(self, call):
        # What `next-release` in the eval suite asks for, on the default window.
        out = await call("get_release_calendar", release_id=50)
        assert out["upcoming"][0]["date"] == day(NEXT_RELEASE_50_OFFSET)

    async def test_a_wide_window_reaches_every_date_for_a_release(self, call):
        # `end` takes absolute dates as well as spans. Spans only run backwards
        # ("5y" is five years ago), so a forward window is written out in full.
        out = await call("get_release_calendar", release_id=50, start="2020-01-01", end="2030-01-01")
        assert len(out["released"]) + len(out["upcoming"]) == len(RELEASE_OFFSETS[50])

    async def test_release_id_narrows_to_one_publication_and_names_it(self, call, fred):
        out = await call("get_release_calendar", release_id=50)
        assert fred.query("/release/dates")["release_id"] == "50"
        assert out["release"]["name"] == "Employment Situation"
        assert {r["release_id"] for r in out["released"] + out["upcoming"]} == {50}

    async def test_relative_dates_work_here_too(self, call, fred):
        await call("get_release_calendar", start="30d", end="today")
        params = fred.query("/releases/dates")
        assert params["realtime_start"] == "2026-07-06"
        assert params["realtime_end"] == TODAY

    async def test_a_backwards_window_is_caught_locally(self, call, fred):
        out = await call("get_release_calendar", start="2026-08-01", end="2026-07-01")
        assert any("swap them" in s for s in out["suggestions"])
        assert not fred.requests
