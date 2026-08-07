"""MCP tools. Each is registered on the server by ``register_all``.

Tools are task-shaped rather than endpoint-shaped: the unit is a question someone
actually asks, so one call can span several FRED endpoints, and the response carries
what was asked for rather than everything the API knows.
"""

import asyncio
import json

import httpx
from mcp.server import MCPServer

from . import dates, shaping
from .client import FredClient
from .errors import guarded_tool
from .schemas import CalendarArgs, GetSeriesArgs, ObservationArgs, RevisionArgs, SearchArgs

# ALFRED's real-time window. Vintage requests need one that spans the whole record;
# with the default (today to today) FRED answers output_type=2 and 4 with
# "No vintage dates exist for the specified real-time period", which reads like the
# series has no revision history rather than like a missing parameter. Every vintage
# call here sets it, which is most of what get_revisions is for.
_ALL_TIME = {"realtime_start": "1776-07-04", "realtime_end": "9999-12-31"}

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


async def _revisions_for_one_date(args: RevisionArgs) -> dict:
    """The full revision history of a single observation."""
    payload = await get_client().get(
        "/series/observations",
        series_id=args.series_id,
        output_type=2,  # one column per vintage
        observation_start=args.observation_date,
        observation_end=args.observation_date,
        **_ALL_TIME,
    )
    rows = payload.get("observations", [])
    if not rows:
        return {
            "series_id": args.series_id,
            "observation_date": args.observation_date,
            "revisions": [],
            "note": "No observation on that date. Check the date against the series' frequency "
            "with get_series; quarterly dates are the first day of the quarter.",
        }

    history = shaping.vintage_history(rows[0], args.series_id)
    result: dict[str, object] = {
        "series_id": args.series_id,
        "observation_date": args.observation_date,
        "revisions": history,
        "revision_count": max(0, len(history) - 1),
    }
    if history:
        result["initial"] = history[0]
        result["current"] = history[-1]
    return result


async def _revision_overview(args: RevisionArgs) -> dict:
    """Initial print against current value, across the most recent observations."""
    client = get_client()
    initial, current, vintages = await asyncio.gather(
        client.get(
            "/series/observations",
            series_id=args.series_id,
            output_type=4,  # initial release only
            limit=args.limit,
            sort_order="desc",
            **_ALL_TIME,
        ),
        client.get("/series/observations", series_id=args.series_id, limit=args.limit, sort_order="desc"),
        client.get("/series/vintagedates", series_id=args.series_id, limit=1, sort_order="desc"),
    )

    rows = shaping.revision_rows(shaping.observation_pairs(initial), shaping.observation_pairs(current))
    vintage_dates = vintages.get("vintage_dates") or []
    return {
        "series_id": args.series_id,
        "observations": rows,
        "revised": sum(1 for row in rows if row.get("revision")),
        "vintages": {"count": vintages.get("count"), "latest": vintage_dates[0] if vintage_dates else None},
        "note": "initial is the number as first published; current is the number today. "
        "Pass observation_date for the full revision history of one of these.",
    }


async def _fetch_release_dates(args: CalendarArgs, start: str, end: str, future: bool) -> dict:
    params: dict[str, object] = {
        "realtime_start": start,
        "realtime_end": end,
        "sort_order": "asc",
        "limit": args.limit,
    }
    # Without this, FRED returns only dates that have already produced data, so the
    # whole "what is scheduled next" half of the question silently comes back empty.
    if future:
        params["include_release_dates_with_no_data"] = True
    if args.release_id is not None:
        return await get_client().get("/release/dates", release_id=args.release_id, **params)
    return await get_client().get("/releases/dates", **params)


def _calendar_rows(payload: dict) -> list[dict]:
    rows = []
    for entry in payload.get("release_dates", []):
        row: dict = {"date": entry.get("date"), "release_id": entry.get("release_id")}
        if entry.get("release_name"):
            row["release_name"] = entry["release_name"]
        rows.append(row)
    return rows


async def _release_calendar(args: CalendarArgs) -> dict:
    """Fetch the two halves of the window separately, then report them separately.

    One request for the whole window would be truncated by ``limit`` before the split,
    and since FRED returns dates ascending, the truncation lands entirely on the
    future. That produced "50 released, 0 upcoming" for a window with 150 scheduled
    releases in it: a confidently empty answer to half the question being asked.
    """
    today = dates.today().isoformat()
    tomorrow = dates.days_after(dates.today(), 1).isoformat()

    past = _fetch_release_dates(args, args.start, min(args.end, today), future=False) if args.start <= today else None
    ahead = _fetch_release_dates(args, max(args.start, tomorrow), args.end, future=True) if args.end > today else None
    release = get_client().get("/release", release_id=args.release_id) if args.release_id is not None else None

    pending = [task for task in (past, ahead, release) if task is not None]
    done = iter(await asyncio.gather(*pending))
    past_payload = next(done) if past is not None else {}
    ahead_payload = next(done) if ahead is not None else {}
    release_payload = next(done) if release is not None else None

    result: dict[str, object] = {
        "window": {"start": args.start, "end": args.end},
        "today": today,
        "released": _calendar_rows(past_payload),
        "upcoming": _calendar_rows(ahead_payload),
        # FRED's totals for each half, so a limited page is visibly a page.
        "totals": {"released": past_payload.get("count", 0), "upcoming": ahead_payload.get("count", 0)},
    }
    if release_payload is not None:
        result["release"] = shaping.trim_release(shaping.first_or_empty(release_payload, "releases"))
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

    @mcp.tool()
    @guarded_tool
    async def get_revisions(series_id: str, observation_date: str = "", limit: int = 10) -> str:
        """What a number was first reported as, and how it has been revised since.

        FRED keeps every vintage of every series (this is ALFRED). Answers questions
        like "what did Q3 GDP originally print at" and "does this series get revised
        much", which the current values alone cannot.

        Two modes:
          observation_date set  the full revision history of that one data point,
                                with the repeated vintages collapsed so you see the
                                changes rather than one column per publication
          observation_date omitted  first-printed against current for the most recent
                                observations, which shows the revision pattern

        observation_date takes the same forms as elsewhere, and must be an observation
        date rather than a publication date: quarterly series are dated to the first
        day of the quarter, monthly to the first of the month.

        The real-time window this needs is set for you. Asking FRED for vintages
        without it fails with a message about no vintage dates existing, which reads
        like the series has no history when the parameter is simply missing.
        """
        args = RevisionArgs.model_validate(
            {"series_id": series_id, "observation_date": observation_date, "limit": limit}
        )
        if args.observation_date:
            return fmt(await _revisions_for_one_date(args))
        return fmt(await _revision_overview(args))

    @mcp.tool()
    @guarded_tool
    async def get_release_calendar(
        start: str = "",
        end: str = "",
        release_id: int | None = None,
        limit: int = 50,
    ) -> str:
        """What economic data just came out, and what is scheduled next.

        Splits results into "released" and "upcoming" around today, because those are
        two different questions and comparing dates to tell them apart is work the
        caller should not have to do.

        Defaults to the last 7 days and the next 14. start and end take the same forms
        as get_observations ("today", "5y", "2026-08", a full date).

        release_id narrows to one publication's schedule, e.g. 50 for the Employment
        Situation. Release IDs come from this tool or from get_series(include=
        ["release"]), and feed back into search_series(release_id=...) to list every
        series a release publishes.
        """
        args = CalendarArgs.model_validate({"start": start, "end": end, "release_id": release_id, "limit": limit})
        return fmt(await _release_calendar(args))
