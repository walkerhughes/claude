"""MCP tools. Each is registered on the server by ``register_all``.

Tools are task-shaped rather than endpoint-shaped: the unit is a question someone
actually asks, so one call can span several FRED endpoints, and the response carries
what was asked for rather than everything the API knows.
"""

import asyncio
import json

import httpx
from mcp.server import MCPServer

from . import shaping
from .client import FredClient
from .errors import guarded_tool
from .schemas import GetSeriesArgs, ObservationArgs, SearchArgs

_client: FredClient | None = None

# Ordering that reads naturally for the field. Popularity descending is the useful
# default; a title sorted from Z is not.
_ASCENDING_ORDERS = {"series_id", "title", "units", "frequency", "seasonal_adjustment", "observation_start"}


def get_client() -> FredClient:
    """Lazy-init the API client so the key is read at tool time, not import time."""
    global _client
    if _client is None:
        _client = FredClient()
    return _client


def reset_state() -> None:
    """Test hook: drop the client singleton."""
    global _client
    _client = None


def fmt(data: object) -> str:
    """Render a tool result as compact, stable JSON."""
    return json.dumps(data, indent=2, default=str)


def _http_detail(exc: httpx.HTTPStatusError) -> str:
    """FRED's own explanation, which the status code alone does not carry."""
    try:
        detail = str(exc.response.json().get("error_message", "")).strip()
    except ValueError:
        detail = ""
    return " ".join(detail.split()) or f"HTTP {exc.response.status_code}"


async def _search_series(args: SearchArgs) -> dict:
    """Run one of the three discovery paths and return the shared output shape."""
    client = get_client()

    params: dict[str, object] = {
        "limit": args.limit,
        "order_by": args.order_by,
        "sort_order": "asc" if args.order_by in _ASCENDING_ORDERS else "desc",
    }
    if args.query:
        params["search_text"] = args.query
        scope = "search"
    elif args.release_id is not None:
        params["release_id"] = args.release_id
        scope = "release"
    else:
        params["category_id"] = args.category_id
        scope = "category"

    # Filters go through tag_names, which takes several at once and is applied by
    # FRED. filter_variable would allow only one per request, leaving the other to be
    # applied here against an already-truncated page and a count that no longer
    # describes what came back.
    if args.tag_names:
        params["tag_names"] = args.tag_names

    payload = await client.get(args.path, **params)
    series = shaping.series_list(payload)

    result: dict[str, object] = {"scope": scope, "count": payload.get("count")}
    filters = {
        k: v
        for k, v in (
            ("frequency", args.frequency),
            ("seasonal_adjustment", args.seasonal_adjustment),
            ("order_by", args.order_by),
        )
        if v
    }
    result["filters"] = filters
    result["returned"] = len(series)
    result["series"] = series
    return result


async def _fetch_one_series(args: GetSeriesArgs, series_id: str) -> dict:
    """Metadata for one series, plus whichever extras were asked for, fetched together.

    A bad ID among good ones fails only its own entry. FRED's "The series does not
    exist" does not say which series it means, so failing the whole call would leave a
    model with several IDs and no idea which to fix.
    """
    client = get_client()

    async def optional(part: str, path: str) -> dict | None:
        if not args.wants(part):
            return None
        return await client.get(path, series_id=series_id)

    try:
        meta, release, categories, tags = await asyncio.gather(
            client.get("/series", series_id=series_id),
            optional("release", "/series/release"),
            optional("categories", "/series/categories"),
            optional("tags", "/series/tags"),
        )
    except httpx.HTTPStatusError as exc:
        return {
            "id": series_id,
            "error": _http_detail(exc),
            "suggestion": "Check this ID with search_series; the others in this call were returned.",
        }

    out = shaping.trim_series(shaping.first_or_empty(meta, "seriess"), notes=args.wants("notes"))
    out.setdefault("id", series_id)
    if release is not None:
        out["release"] = shaping.trim_release(shaping.first_or_empty(release, "releases"))
    if categories is not None:
        out["categories"] = [shaping.trim_category(c) for c in categories.get("categories", [])]
    if tags is not None:
        out["tags"] = shaping.tag_names(tags.get("tags", []))
    return out


Pairs = list[tuple[str, shaping.Number]]


async def _observations_for(args: ObservationArgs, series_id: str) -> tuple[str, Pairs | str]:
    """One series' observations, or its own error message. A bad ID among good ones
    should cost only its own column, not the whole comparison."""
    try:
        payload = await get_client().get(
            "/series/observations",
            series_id=series_id,
            observation_start=args.start,
            observation_end=args.end,
            units=args.units,
            frequency=args.frequency,
            # FRED ignores this unless frequency is set, so sending it always is safe.
            aggregation_method=args.aggregation_method,
            sort_order="asc",
        )
    except httpx.HTTPStatusError as exc:
        return series_id, _http_detail(exc)
    return series_id, shaping.observation_pairs(payload)


async def _get_observations(args: ObservationArgs) -> dict:
    fetched = await asyncio.gather(*(_observations_for(args, sid) for sid in args.series_ids))

    per_series: dict[str, Pairs] = {}
    errors: dict[str, str] = {}
    for series_id, outcome in fetched:
        if isinstance(outcome, str):
            errors[series_id] = outcome
        else:
            per_series[series_id] = outcome

    # Summaries first, over every observation. Downsampling after, so a thinned series
    # still reports its true latest value and true extremes.
    summary = {series_id: shaping.summarize(pairs) for series_id, pairs in per_series.items()}
    dates, columns = shaping.align(per_series)
    total = len(dates)
    dates, columns, dropped = shaping.downsample(dates, columns, args.max_points)

    points: dict[str, object] = {"returned": len(dates), "total": total, "dropped": dropped}
    if dropped:
        points["note"] = "evenly spaced sample; the summary covers every observation"

    result: dict[str, object] = {
        "units": args.units,
        "units_meaning": args.units_meaning,
        "dates": dates,
        "values": columns,
        "summary": summary,
        "points": points,
    }
    if args.frequency:
        result["frequency"] = args.frequency
        result["aggregation_method"] = args.aggregation_method
    if errors:
        result["errors"] = errors
    return result


def register_all(mcp: MCPServer) -> None:
    """Register every tool on the given MCP server."""

    @mcp.tool()
    @guarded_tool
    async def search_series(
        query: str = "",
        release_id: int | None = None,
        category_id: int | None = None,
        limit: int = 10,
        frequency: str = "",
        seasonal_adjustment: str = "",
        order_by: str = "popularity",
    ) -> str:
        """Find FRED series. Start here: series are named by opaque IDs like CPIAUCSL.

        Supply exactly one of:
          query        free-text search, e.g. "unemployment rate", "10 year treasury"
          release_id   every series in a release (get IDs from get_release_calendar)
          category_id  every series in a category (0 is the FRED root)

        Results are ordered by popularity by default, so the canonical series comes
        first. FRED's own default buries UNRATE under hundreds of regional variants.

        frequency accepts words or codes: "monthly"/"m", "quarterly"/"q", "annual"/"a",
        "daily"/"d", "weekly"/"w", "biweekly"/"bw", "semiannual"/"sa".
        seasonal_adjustment accepts "SA", "NSA", "seasonally adjusted", "unadjusted".

        Returns the total match count alongside the page, so you can tell 10-of-12 from
        10-of-53,486. Series notes are omitted here; use get_series for those.
        """
        return fmt(
            await _search_series(
                SearchArgs(
                    query=query,
                    release_id=release_id,
                    category_id=category_id,
                    limit=limit,
                    frequency=frequency,
                    seasonal_adjustment=seasonal_adjustment,
                    order_by=order_by,
                )
            )
        )

    # series_ids and include are typed as list-or-string on purpose. The MCP layer
    # validates against the annotation before the tool body runs, so a strict
    # list[str] turns get_series("UNRATE") into a raw ToolError that never reaches
    # the correction layer, which is the exact failure the correction layer exists
    # to prevent. The docstring still tells the model a list is the expected form.
    @mcp.tool()
    @guarded_tool
    async def get_series(series_ids: list[str] | str, include: list[str] | str | None = None) -> str:
        """Explain what one or more series measure, before charting or comparing them.

        Answers the questions that decide whether a number means what you think:
        the units (percent? billions? an index?), the frequency, whether it is
        seasonally adjusted, the period it covers, and when it was last updated.

        series_ids is case-insensitive here and up to 20 at a time.

        include controls how much comes back, defaulting to ["metadata"]:
          metadata    units, frequency, seasonal adjustment, coverage, last update
          notes       the full definition, including which survey it comes from
          release     the publication it belongs to, with a link to the press release
          categories  where it sits in the FRED category tree
          tags        FRED's tags for the series
        Pass "all" for everything.

        A bad ID among good ones fails only its own entry; the rest are still returned.
        """
        # model_validate, not the constructor: the before-validator is what accepts a
        # bare string, and only this entry point is typed loosely enough to reach it.
        args = GetSeriesArgs.model_validate({"series_ids": series_ids, "include": include or ["metadata"]})
        results = await asyncio.gather(*(_fetch_one_series(args, sid) for sid in args.series_ids))
        return fmt({"series": list(results)})

    @mcp.tool()
    @guarded_tool
    async def get_observations(
        series_ids: list[str] | str,
        start: str = "",
        end: str = "",
        units: str = "lin",
        frequency: str = "",
        aggregation_method: str = "avg",
        max_points: int = 120,
    ) -> str:
        """Get the actual numbers. Pass several series at once to compare them.

        Series come back on one shared date index, so a comparison is a single call:
        {"dates": [...], "values": {"UNRATE": [...], "CPIAUCSL": [...]}}. Where a
        series has no observation for a date (a quarterly series against a monthly
        one) the value is null rather than filled in.

        start and end accept YYYY-MM-DD, a bare year ("2020"), a year-month
        ("2020-01"), a span back from today ("5y", "18 months", "last 10 years"),
        "ytd", or "today". Omit both for the full history.

        units transforms the series server-side, so do not do this arithmetic
        yourself. Say "yoy" for year-over-year percent change (FRED calls it pc1),
        "percent change" for period-over-period, "change" for a difference,
        "annualized", or "level" for the published numbers.

        frequency aggregates to a coarser interval only ("monthly", "quarterly",
        "annual"), with aggregation_method of avg, sum, or eop.

        Every series gets a summary (latest, prior, change, min, max, mean, count)
        computed over ALL its observations. Only the returned point list is thinned
        to max_points, so a 20-year daily series still reports its true extremes
        without spending 5,000 points to do it.
        """
        args = ObservationArgs.model_validate(
            {
                "series_ids": series_ids,
                "start": start,
                "end": end,
                "units": units,
                "frequency": frequency,
                "aggregation_method": aggregation_method,
                "max_points": max_points,
            }
        )
        return fmt(await _get_observations(args))
