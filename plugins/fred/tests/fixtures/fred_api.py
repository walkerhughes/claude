"""A mock FRED API.

One routing function, three callers: the unit tests drive it through an httpx
transport, the integration tests drive the real MCP tools through the same transport,
and the eval benchmark serves it over HTTP inside the container. Everything scores
against identical fixture behaviour, so a benchmark answer can never disagree with a
test answer.

Responses are trimmed captures from the real API, so the shapes the shaping layer is
asserted against are FRED's rather than ones invented to match the code.

Serve it (this is what the benchmark container runs):

    python -m tests.fixtures.fred_api 8080
"""

import json
import math
from datetime import date, timedelta

import httpx

# The clock the tests pin. Release dates are generated relative to a clock rather than
# written down, because the calendar's whole job is "what came out and what is next":
# fixed dates stop straddling today the moment the fixture ages, and the benchmark
# runs on whatever day CI happens to run.
FIXED_TODAY = date(2026, 8, 5)

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

DGS10 = {
    **UNRATE,
    "id": "DGS10",
    "title": "Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity",
    "frequency": "Daily",
    "frequency_short": "D",
    "units": "Percent",
    "popularity": 88,
}

SERIES = {s["id"]: s for s in (UNRATE, CPIAUCSL, UNRATENSA, GDPC1, DGS10)}

# Every series in the Employment Situation release (id 50). Three monthly, one
# quarterly, so a frequency filter over a release has something to actually filter.
RELEASE_50_SERIES = [UNRATE, CPIAUCSL, UNRATENSA, GDPC1]

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


def _monthly(start: date, count: int, first: float, step: float) -> list[tuple[str, str]]:
    rows = []
    for i in range(count):
        month = start.month - 1 + i
        stamp = date(start.year + month // 12, month % 12 + 1, 1)
        rows.append((stamp.isoformat(), f"{first + step * i:.4f}"))
    return rows


# 26 months, which is what makes a year-over-year transform expressible at all: pc1
# needs an observation twelve months back, and a six-point series has none.
CPI_OBS = _monthly(date(2024, 1, 1), 26, 100.0, 0.25)


# A long daily series, five years of it, for the downsampling tests and for the
# `rate-history-max` eval task.
#
# The extremes are single-day spikes at indices that downsampling does not sample. That
# is deliberate and it is the whole point: the summary is computed over every
# observation and only the point list is thinned, so the true extremes have to be
# reachable from the summary and *unreachable* from the points. An earlier version used
# a broad triangular peak, and the sampling grid happened to land exactly on it, so a
# lazy agent reading the returned points got the right answer and the task proved
# nothing. `test_the_extremes_are_not_in_the_returned_points` now fails if that
# regresses.
_DAILY_DAYS = 1827
_SPIKE_INDEX, _TROUGH_INDEX = 900, 1200
DAILY_MIN, DAILY_MAX = 20.0, 300.0


def _daily_series() -> list[tuple[str, str]]:
    # A slow wave for the body of the series, well inside the extremes.
    values = [130 + 70 * math.sin(2 * math.pi * i / 900) for i in range(_DAILY_DAYS)]
    values[_SPIKE_INDEX] = DAILY_MAX
    values[_TROUGH_INDEX] = DAILY_MIN

    first = date(2020, 1, 1).toordinal()
    return [(date.fromordinal(first + i).isoformat(), f"{v:.4f}") for i, v in enumerate(values)]


DAILY_OBS = _daily_series()

OBSERVATIONS = {"UNRATE": UNRATE_OBS, "GDPC1": GDPC1_OBS, "CPIAUCSL": CPI_OBS, "DGS10": DAILY_OBS}

# What FRED returns for output_type=4: the value as first published. GDPC1's first
# quarter was revised; its second stands as published, and UNRATE is never revised.
INITIAL_OBS = {
    "GDPC1": [("2025-01-01", "22900.0"), ("2025-04-01", "23150.5")],
    "UNRATE": UNRATE_OBS,
    "CPIAUCSL": CPI_OBS,
    "DGS10": DAILY_OBS,
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

RELEASES = {
    50: {"id": 50, "name": "Employment Situation", "link": "http://www.bls.gov/ces/", "press_release": True},
    10: {"id": 10, "name": "Consumer Price Index", "link": "http://www.bls.gov/cpi/", "press_release": True},
}

# Offsets in days from "today". Chosen so the calendar's default window (7 days back,
# 14 forward) holds three released dates including one dated exactly today, and two
# upcoming ones, with dates outside the window on both sides to prove it filters.
RELEASE_OFFSETS = {50: (-33, -5, 9, 37), 10: (-12, -2, 0, 12, 40)}
# The offset `next-release` expects for release 50: the first one still ahead.
NEXT_RELEASE_50_OFFSET = 9


def release_dates(today: date) -> list[dict]:
    """Every release date, ascending, relative to the given day."""
    rows = [
        {
            "release_id": release_id,
            "release_name": RELEASES[release_id]["name"],
            "date": (today + timedelta(days=offset)).isoformat(),
        }
        for release_id, offsets in RELEASE_OFFSETS.items()
        for offset in offsets
    ]
    return sorted(rows, key=lambda r: (r["date"], r["release_id"]))


# --- units transforms ----------------------------------------------------------------
#
# The mock applies these for real. Echoing the requested units while returning raw
# levels would make `units="yoy"` indistinguishable from not passing units at all,
# which is exactly the correction the eval task exists to measure.


def _a_year_before(stamp: str) -> str:
    day = date.fromisoformat(stamp)
    try:
        return day.replace(year=day.year - 1).isoformat()
    except ValueError:  # 29 February
        return day.replace(year=day.year - 1, day=28).isoformat()


def transform(rows: list[tuple[str, str]], units: str) -> list[tuple[str, str]]:
    """Apply a FRED units code. Values that cannot be computed become ".", as FRED does."""
    if units in ("", "lin"):
        return rows

    values = {stamp: (None if raw == "." else float(raw)) for stamp, raw in rows}
    order = [stamp for stamp, _ in rows]
    previous = {stamp: order[i - 1] if i else None for i, stamp in enumerate(order)}

    out: list[tuple[str, str]] = []
    for stamp, _ in rows:
        current = values.get(stamp)
        base_key = _a_year_before(stamp) if units in ("pc1", "ch1") else previous[stamp]
        base = values.get(base_key) if base_key else None

        if current is None or base is None:
            out.append((stamp, "."))
            continue
        if units in ("chg", "ch1"):
            out.append((stamp, f"{current - base:.5f}"))
        elif units in ("pch", "pc1"):
            out.append((stamp, "." if base == 0 else f"{(current - base) / base * 100:.5f}"))
        else:  # anything else is returned as published rather than silently faked
            out.append((stamp, f"{current:.5f}"))
    return out


# --- routing -------------------------------------------------------------------------


def _error(status: int, message: str) -> tuple[int, dict]:
    return status, {"error_code": status, "error_message": message}


def _tags_for(series: dict) -> set[str]:
    """The freq and seas tags FRED would carry for a series, derived from its fields."""
    return {series["frequency"].lower(), "nsa" if series["seasonal_adjustment_short"] == "NSA" else "sa"}


def _limited(rows: list, params: dict[str, str]) -> list:
    if params.get("sort_order") == "desc":
        rows = sorted(rows, reverse=True)
    return rows[: int(params.get("limit", 100000))]


def route(path: str, params: dict[str, str], today: date | None = None) -> tuple[int, dict]:
    """Answer one FRED request. Pure: no I/O, no globals, no clock of its own."""
    now = today or date.today()
    path = path.rstrip("/")

    # Exact, not endswith: /release/series and /category/series also end in "/series".
    if path.endswith("/fred/series"):
        return _one_series(params.get("series_id", ""))
    if path.endswith("/series/observations"):
        return _observations(params, now)
    if path.endswith("/series/vintagedates"):
        return 200, {"count": len(VINTAGE_DATES), "vintage_dates": VINTAGE_DATES[: int(params.get("limit", 100))]}
    if path.endswith("/series/search"):
        return _series_list(params, [UNRATE, UNRATENSA, CPIAUCSL, GDPC1, DGS10])
    if path.endswith("/release/series"):
        pool = RELEASE_50_SERIES if params.get("release_id") == "50" else []
        return _series_list(params, pool)
    if path.endswith("/category/series"):
        return _series_list(params, [UNRATE, CPIAUCSL])
    if path.endswith("/series/release"):
        return 200, {"releases": [RELEASES[50]]}
    if path.endswith("/series/categories"):
        return 200, {
            "categories": [
                {"id": 32447, "name": "Unemployment Rate", "parent_id": 12, "notes": "Unemployed over labor force."}
            ]
        }
    if path.endswith("/series/tags"):
        return 200, {
            "count": 2,
            "tags": [
                {"name": "headline figure", "group_id": "gen", "notes": "", "popularity": 51},
                {"name": "monthly", "group_id": "freq", "notes": "", "popularity": 93},
            ],
        }
    if path.endswith("/releases/dates"):
        return _release_dates(params, release_dates(now), now)
    if path.endswith("/release/dates"):
        # FRED omits release_name here, unlike /releases/dates.
        rows = [
            {"release_id": r["release_id"], "date": r["date"]}
            for r in release_dates(now)
            if str(r["release_id"]) == params.get("release_id")
        ]
        return _release_dates(params, rows, now)
    if path.endswith("/fred/release"):
        release = RELEASES.get(int(params.get("release_id", 0) or 0))
        if release is None:
            return _error(400, "Bad Request.  The release does not exist.")
        return 200, {"releases": [release]}
    return _error(404, f"Not Found. No handler for {path}.")


def _one_series(series_id: str) -> tuple[int, dict]:
    if series_id not in SERIES:
        return _error(400, "Bad Request.  The series does not exist.")
    return 200, {"realtime_start": "2026-08-05", "realtime_end": "2026-08-05", "seriess": [SERIES[series_id]]}


def _observations(params: dict[str, str], now: date) -> tuple[int, dict]:
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
                f"{now.isoformat()} to {now.isoformat()}.",
            )
        if output_type == "2":
            row = VINTAGE_ROW if params.get("observation_start") == VINTAGE_ROW["date"] else None
            return 200, {"observations": [row] if row else []}
        return _payload(_limited(INITIAL_OBS.get(series_id, []), params), params)

    rows = transform(OBSERVATIONS[series_id], params.get("units", "lin"))
    start, end = params.get("observation_start"), params.get("observation_end")
    if start:
        rows = [r for r in rows if r[0] >= start]
    if end:
        rows = [r for r in rows if r[0] <= end]
    return _payload(_limited(rows, params), params)


def _payload(rows: list[tuple[str, str]], params: dict[str, str]) -> tuple[int, dict]:
    # Real-time fields carry the same value on every row, which is the redundancy the
    # columnar shaping exists to remove; the fixture reproduces it faithfully.
    stamp = "2026-08-05"
    return 200, {
        "realtime_start": stamp,
        "realtime_end": stamp,
        "units": params.get("units", "lin"),
        "count": len(rows),
        "observations": [{"realtime_start": stamp, "realtime_end": stamp, "date": d, "value": v} for d, v in rows],
    }


def _series_list(params: dict[str, str], pool: list[dict]) -> tuple[int, dict]:
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
    return 200, {"count": total, "offset": 0, "limit": limit, "seriess": rows[:limit]}


def _release_dates(params: dict[str, str], pool: list[dict], now: date) -> tuple[int, dict]:
    rows = list(pool)
    start, end = params.get("realtime_start"), params.get("realtime_end")
    if start:
        rows = [r for r in rows if r["date"] >= start]
    if end:
        rows = [r for r in rows if r["date"] <= end]
    # FRED only returns scheduled dates that have not produced data yet when this flag
    # is set, so the fixture withholds them without it.
    if params.get("include_release_dates_with_no_data") != "true":
        rows = [r for r in rows if r["date"] <= now.isoformat()]
    return 200, {"count": len(rows), "release_dates": rows[: int(params.get("limit", 1000))]}


# --- callers -------------------------------------------------------------------------


class MockFred:
    """httpx transport over ``route``, recording every request the tests assert on."""

    def __init__(self, today: date = FIXED_TODAY) -> None:
        self.today = today
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
        params = dict(request.url.params)
        self.requests.append((request.url.path, params))
        status, body = route(request.url.path, params, self.today)
        return httpx.Response(status, json=body)


def serve(port: int = 8080) -> None:
    """Serve the mock over HTTP. This is what the benchmark container runs.

    stdlib only, on purpose: the plugin's own dependencies are mcp, httpx and pydantic,
    and the benchmark should not be the reason a web framework joins them.
    """
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlparse

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802  (stdlib's spelling)
            parsed = urlparse(self.path)
            params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            status, body = route(parsed.path, params)
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: object) -> None:
            pass  # quiet: the container's log is for the agent, not for request lines

    HTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    import sys

    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 8080)


# Kept for the tests that assert against the pinned clock.
TODAY = FIXED_TODAY.isoformat()
