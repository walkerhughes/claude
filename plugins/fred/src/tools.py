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
from .schemas import GetSeriesArgs, SearchArgs

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
        detail = ""
        try:
            detail = str(exc.response.json().get("error_message", "")).strip()
        except ValueError:
            pass
        return {
            "id": series_id,
            "error": " ".join(detail.split()) or f"HTTP {exc.response.status_code}",
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
