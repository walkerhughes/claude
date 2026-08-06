"""A mock FRED API, as an httpx transport.

Responses are trimmed captures from the real API, so the shapes the shaping layer is
asserted against are FRED's rather than ones invented to match the code. The whole
thing is a routing function because that is all the integration tests need: no server,
no port, no ASGI app.

Every handler records the query it was called with, which is how the tests check that
the tools send the parameters they claim to (the real-time window on a vintage request,
the filter_variable pairing, the popularity ordering).
"""

from datetime import date

import httpx

UNRATE = {
    "id": "UNRATE",
    "realtime_start": "2026-08-05",
    "realtime_end": "2026-08-05",
    "title": "Unemployment Rate",
    "observation_start": "1948-01-01",
    "observation_end": "2026-06-01",
    "frequency": "Monthly",
    "frequency_short": "M",
    "units": "Percent",
    "units_short": "%",
    "seasonal_adjustment": "Seasonally Adjusted",
    "seasonal_adjustment_short": "SA",
    "last_updated": "2026-07-02 08:31:40-05",
    "popularity": 96,
    "group_popularity": 96,
    "notes": "The unemployment rate represents the number of unemployed as a percentage\r\n\r\nof the labor force.",
}

CPIAUCSL = {
    "id": "CPIAUCSL",
    "realtime_start": "2026-08-05",
    "realtime_end": "2026-08-05",
    "title": "Consumer Price Index for All Urban Consumers: All Items in U.S. City Average",
    "observation_start": "1947-01-01",
    "observation_end": "2026-06-01",
    "frequency": "Monthly",
    "frequency_short": "M",
    "units": "Index 1982-1984=100",
    "units_short": "Index 1982-1984=100",
    "seasonal_adjustment": "Seasonally Adjusted",
    "seasonal_adjustment_short": "SA",
    "last_updated": "2026-07-15 07:41:02-05",
    "popularity": 92,
    "group_popularity": 92,
    "notes": "The CPI measures the average change in prices.",
}

UNRATENSA = {
    **UNRATE,
    "id": "UNRATENSA",
    "title": "Unemployment Rate (Not Seasonally Adjusted)",
    "seasonal_adjustment": "Not Seasonally Adjusted",
    "seasonal_adjustment_short": "NSA",
    "popularity": 60,
}

GDPC1 = {
    **UNRATE,
    "id": "GDPC1",
    "title": "Real Gross Domestic Product",
    "frequency": "Quarterly",
    "frequency_short": "Q",
    "units": "Billions of Chained 2017 Dollars",
    "popularity": 90,
}

SERIES = {s["id"]: s for s in (UNRATE, CPIAUCSL, UNRATENSA, GDPC1)}

# Monthly, with a "." in the middle: FRED's missing-value marker, not a null.
UNRATE_OBS = [
    ("2025-01-01", "4.0"),
    ("2025-02-01", "4.1"),
    ("2025-03-01", "."),
    ("2025-04-01", "4.2"),
    ("2025-05-01", "4.4"),
    ("2025-06-01", "4.3"),
]

# Quarterly, so it lines up with UNRATE on only two of its dates. This is the pair the
# alignment tests use: a union index with nulls where a series has no observation.
GDPC1_OBS = [
    ("2025-01-01", "23000.0"),
    ("2025-04-01", "23150.5"),
]

# A long daily series for the downsampling tests. The knots put the peak and the trough
# in the *interior*, away from the first and last points that downsampling always keeps.
# That is the whole point: a summary computed after thinning would report the extremes
# of the sample, and with extremes at the endpoints the test could not tell the
# difference.
_DAILY_KNOTS = [(0, 200.0), (80, 300.0), (200, 50.0), (365, 180.0)]


def _daily_series() -> list[tuple[str, str]]:
    values: list[float] = []
    for (i0, v0), (i1, v1) in zip(_DAILY_KNOTS, _DAILY_KNOTS[1:]):
        values.extend(v0 + (v1 - v0) * (i - i0) / (i1 - i0) for i in range(i0, i1))
    values.append(_DAILY_KNOTS[-1][1])

    first = date(2020, 1, 1).toordinal()
    return [(date.fromordinal(first + i).isoformat(), f"{v:.4f}") for i, v in enumerate(values)]


DAILY_OBS = _daily_series()
DAILY_MIN, DAILY_MAX = 50.0, 300.0

OBSERVATIONS = {"UNRATE": UNRATE_OBS, "GDPC1": GDPC1_OBS, "CPIAUCSL": UNRATE_OBS, "DGS10": DAILY_OBS}

# What FRED returns for output_type=4: the value as first published, with the realtime
# window showing when that print was current. GDPC1 gets revised, UNRATE does not.
INITIAL_OBS = {
    # 2025-01-01 was revised (22900 -> 23000); 2025-04-01 stands as first published.
    # One of each, so "revised" counting is tested against a mix rather than a
    # uniformly-revised series where an off-by-one would pass.
    "GDPC1": [("2025-01-01", "22900.0"), ("2025-04-01", "23150.5")],
    "UNRATE": UNRATE_OBS,
    "CPIAUCSL": UNRATE_OBS,
}

# One column per vintage, the output_type=2 shape. Six vintages, one real revision:
# the collapse should reduce this to two entries, not six.
VINTAGE_ROW = {
    "date": "2025-01-01",
    "GDPC1_20250430": "22900.0",
    "GDPC1_20250528": "22900.0",
    "GDPC1_20250625": "22900.0",
    "GDPC1_20250730": "23000.0",
    "GDPC1_20250828": "23000.0",
    "GDPC1_20250925": "23000.0",
}

VINTAGE_DATES = ["2025-09-25", "2025-08-28", "2025-07-30", "2025-06-25", "2025-05-28", "2025-04-30"]

# Dates straddle TODAY so the released/upcoming split has something on both sides.
TODAY = "2026-08-05"
RELEASE_DATES = [
    {"release_id": 50, "release_name": "Employment Situation", "date": "2026-08-01"},
    {"release_id": 10, "release_name": "Consumer Price Index", "date": "2026-08-05"},
    {"release_id": 50, "release_name": "Employment Situation", "date": "2026-08-07"},
    {"release_id": 10, "release_name": "Consumer Price Index", "date": "2026-08-12"},
]


class MockFred:
    """Routes FRED paths to captured payloads and records every request."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, str]]] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def query(self, path_suffix: str) -> dict[str, str]:
        """The most recent query recorded for a path ending in ``path_suffix``."""
        for path, params in reversed(self.requests):
            if path.endswith(path_suffix):
                return params
        raise AssertionError(f"no request recorded for {path_suffix}; saw {[p for p, _ in self.requests]}")

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = dict(request.url.params)
        self.requests.append((path, params))

        # Exact, not endswith: /release/series and /category/series also end in
        # "/series" and would otherwise be swallowed by this branch.
        if path.endswith("/fred/series"):
            return self._one_series(params.get("series_id", ""))
        if path.endswith("/series/observations"):
            return self._observations(params)
        if path.endswith("/series/vintagedates"):
            return _ok({"count": len(VINTAGE_DATES), "vintage_dates": VINTAGE_DATES[: int(params.get("limit", 100))]})
        if path.endswith("/releases/dates"):
            return self._release_dates(params, RELEASE_DATES)
        if path.endswith("/release/dates"):
            # FRED omits release_name here, unlike /releases/dates.
            rows = [
                {"release_id": r["release_id"], "date": r["date"]}
                for r in RELEASE_DATES
                if str(r["release_id"]) == params.get("release_id")
            ]
            return self._release_dates(params, rows)
        if path.endswith("/fred/release"):
            return _ok({"releases": [{"id": 50, "name": "Employment Situation", "link": "http://www.bls.gov/ces/"}]})
        if path.endswith("/series/search"):
            return self._series_list(params, [UNRATE, UNRATENSA, CPIAUCSL, GDPC1])
        if path.endswith("/release/series") or path.endswith("/category/series"):
            return self._series_list(params, [UNRATE, CPIAUCSL])
        if path.endswith("/series/release"):
            return _ok(
                {
                    "releases": [
                        {
                            "id": 50,
                            "realtime_start": "2026-08-05",
                            "realtime_end": "2026-08-05",
                            "name": "Employment Situation",
                            "press_release": True,
                            "link": "http://www.bls.gov/ces/",
                        }
                    ]
                }
            )
        if path.endswith("/series/categories"):
            return _ok(
                {
                    "categories": [
                        {
                            "id": 32447,
                            "name": "Unemployment Rate",
                            "parent_id": 12,
                            "notes": "The ratio of unemployed to the civilian labor force.",
                        }
                    ]
                }
            )
        if path.endswith("/series/tags"):
            return _ok(
                {
                    "count": 2,
                    "tags": [
                        {"name": "headline figure", "group_id": "gen", "notes": "", "popularity": 51},
                        {"name": "monthly", "group_id": "freq", "notes": "", "popularity": 93},
                    ],
                }
            )
        return _error(404, f"Not Found. No handler for {path}.")

    def _observations(self, params: dict[str, str]) -> httpx.Response:
        series_id = params.get("series_id", "")
        if series_id not in OBSERVATIONS:
            return _error(400, "Bad Request.  The series does not exist.")

        output_type = params.get("output_type", "1")
        if output_type in ("2", "4"):
            # FRED's own behaviour, and the reason get_revisions exists: without a
            # real-time window spanning the record, a vintage request fails.
            if params.get("realtime_start") != "1776-07-04":
                return _error(
                    400,
                    "Bad Request.  No vintage dates exist for the specified real-time period: "
                    f"{TODAY} to {TODAY}.",
                )
            if output_type == "2":
                row = VINTAGE_ROW if params.get("observation_start") == VINTAGE_ROW["date"] else None
                return _ok({"observations": [row] if row else []})
            rows = INITIAL_OBS.get(series_id, [])
            return self._observation_payload(_limited(rows, params), params)

        rows = OBSERVATIONS[series_id]
        start, end = params.get("observation_start"), params.get("observation_end")
        if start:
            rows = [r for r in rows if r[0] >= start]
        if end:
            rows = [r for r in rows if r[0] <= end]
        return self._observation_payload(_limited(rows, params), params)

    def _observation_payload(self, rows: list[tuple[str, str]], params: dict[str, str]) -> httpx.Response:
        # Real-time fields carry the same value on every row, which is the redundancy
        # the columnar shaping exists to remove; the fixture reproduces it faithfully.
        return _ok(
            {
                "realtime_start": TODAY,
                "realtime_end": TODAY,
                "units": params.get("units", "lin"),
                "count": len(rows),
                "observations": [
                    {"realtime_start": TODAY, "realtime_end": TODAY, "date": d, "value": v} for d, v in rows
                ],
            }
        )

    def _one_series(self, series_id: str) -> httpx.Response:
        if series_id not in SERIES:
            return _error(400, "Bad Request.  The series does not exist.")
        return _ok({"realtime_start": "2026-08-05", "realtime_end": "2026-08-05", "seriess": [SERIES[series_id]]})

    def _series_list(self, params: dict[str, str], pool: list[dict]) -> httpx.Response:
        """Applies FRED's tag filter, its ordering, and its limit."""
        rows = list(pool)
        for tag in filter(None, params.get("tag_names", "").split(";")):
            rows = [r for r in rows if tag in _tags_for(r)]

        order_by = params.get("order_by", "series_id")
        reverse = params.get("sort_order", "asc") == "desc"
        if order_by in {"popularity", "group_popularity"}:
            rows.sort(key=lambda r: r.get(order_by, 0), reverse=reverse)
        else:
            rows.sort(key=lambda r: str(r.get(order_by, r["id"])), reverse=reverse)

        total = len(rows)
        limit = int(params.get("limit", 1000))
        return _ok({"count": total, "offset": 0, "limit": limit, "seriess": rows[:limit]})


    def _release_dates(self, params: dict[str, str], pool: list[dict]) -> httpx.Response:
        rows = list(pool)
        start, end = params.get("realtime_start"), params.get("realtime_end")
        if start:
            rows = [r for r in rows if r["date"] >= start]
        if end:
            rows = [r for r in rows if r["date"] <= end]
        # FRED only returns scheduled dates that have not produced data yet when this
        # flag is set, so the fixture withholds them without it.
        if params.get("include_release_dates_with_no_data") != "true":
            rows = [r for r in rows if r["date"] <= TODAY]
        return _ok({"count": len(rows), "release_dates": rows[: int(params.get("limit", 1000))]})


def _limited(rows: list[tuple[str, str]], params: dict[str, str]) -> list[tuple[str, str]]:
    """FRED's limit and sort_order, applied the way the real API does."""
    if params.get("sort_order") == "desc":
        rows = sorted(rows, reverse=True)
    limit = int(params.get("limit", 100000))
    return rows[:limit]


def _tags_for(series: dict) -> set[str]:
    """The freq and seas tags FRED would carry for a series, derived from its fields."""
    return {
        series["frequency"].lower(),
        "nsa" if series["seasonal_adjustment_short"] == "NSA" else "sa",
    }


def _ok(payload: dict) -> httpx.Response:
    return httpx.Response(200, json=payload)


def _error(status: int, message: str) -> httpx.Response:
    return httpx.Response(status, json={"error_code": status, "error_message": message})
