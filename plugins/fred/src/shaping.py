"""Trim FRED payloads to what a model reads.

A FRED series object carries 16 fields, four of which are shorthand duplicates of
another four, two of which (``realtime_start``, ``realtime_end``) are the same value on
every row of a normal response, and one of which (``notes``) can run to several
paragraphs. Ten search results at full fidelity is a few thousand tokens spent to pick
one ID.
"""

from typing import Any

# Kept from a FRED series object, in the order a model reads them: what it is, then
# what the numbers mean, then whether the data is current.
_SERIES_FIELDS = (
    "id",
    "title",
    "units",
    "frequency",
    "observation_start",
    "observation_end",
    "last_updated",
    "popularity",
)


def trim_series(raw: dict, *, notes: bool = False) -> dict:
    """One series object, reduced to the fields worth spending tokens on.

    ``seasonal_adjustment`` is carried as the SA/NSA shorthand, which is unambiguous
    and a fifth the length of the phrase. ``notes`` is opt-in: it is the single largest
    field and is not what anyone is reading a *list* of series for.
    """
    out = {field: raw[field] for field in _SERIES_FIELDS if raw.get(field) is not None}
    if raw.get("seasonal_adjustment_short"):
        out["seasonal_adjustment"] = raw["seasonal_adjustment_short"]
    if notes and raw.get("notes"):
        out["notes"] = " ".join(str(raw["notes"]).split())
    return out


def trim_release(raw: dict) -> dict:
    """A release object: who publishes the series and where to read the press release."""
    out = {"id": raw.get("id"), "name": raw.get("name")}
    if raw.get("link"):
        out["link"] = raw["link"]
    if raw.get("press_release") is not None:
        out["press_release"] = raw["press_release"]
    return out


def trim_category(raw: dict) -> dict:
    return {"id": raw.get("id"), "name": raw.get("name")}


def tag_names(raw_tags: list[dict]) -> list[str]:
    """Tags are only useful as names here; the group, notes, and counts are not read."""
    return [tag["name"] for tag in raw_tags if tag.get("name")]


def series_list(payload: dict, *, notes: bool = False) -> list[dict]:
    """The ``seriess`` array that /series, /series/search, /release/series and
    /category/series all return under the same misspelled key."""
    return [trim_series(item, notes=notes) for item in payload.get("seriess", [])]


def first_or_empty(payload: dict, key: str) -> dict[str, Any]:
    items = payload.get(key) or []
    return items[0] if items else {}


# --- observations ------------------------------------------------------------------
#
# FRED returns one object per observation:
#
#     {"realtime_start": "2026-08-05", "realtime_end": "2026-08-05",
#      "date": "2025-01-01", "value": "2.99098"}
#
# On a normal (non-vintage) request the two realtime fields hold the same value on
# every single row, and the key names repeat once per observation. Twenty years of a
# daily series is around 5,000 of those. Columnar output drops all of it.

Number = float | None


def parse_value(raw: object) -> Number:
    """FRED writes values as strings and missing ones as ".", not null."""
    if raw is None:
        return None
    text = str(raw).strip()
    if text in ("", "."):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def observation_pairs(payload: dict) -> list[tuple[str, Number]]:
    """(date, value) for each observation, values parsed."""
    return [(obs["date"], parse_value(obs.get("value"))) for obs in payload.get("observations", []) if obs.get("date")]


def align(per_series: dict[str, list[tuple[str, Number]]]) -> tuple[list[str], dict[str, list[Number]]]:
    """Put several series on one shared, sorted date index.

    This is what makes comparison a single tool call. A monthly and a quarterly series
    will not line up, so the index is the union of their dates and the gaps are null
    rather than silently dropped or forward-filled, which would invent data.
    """
    dates = sorted({d for pairs in per_series.values() for d, _ in pairs})
    index = {date: position for position, date in enumerate(dates)}

    columns: dict[str, list[Number]] = {}
    for series_id, pairs in per_series.items():
        column: list[Number] = [None] * len(dates)
        for date, value in pairs:
            column[index[date]] = value
        columns[series_id] = column
    return dates, columns


def summarize(pairs: list[tuple[str, Number]]) -> dict:
    """The figures worth having, computed over every observation.

    Deliberately computed *before* downsampling. A 5,000-point daily series thinned to
    120 still reports its true min, max, and latest value; a summary computed after
    would quietly report the extremes of the sample instead of the series.
    """
    observed = [(date, value) for date, value in pairs if value is not None]
    if not observed:
        return {"observations": len(pairs), "count": 0}

    values = [value for _, value in observed]
    latest_date, latest = observed[-1]
    summary: dict[str, Any] = {
        "latest": latest,
        "latest_date": latest_date,
        "min": min(values),
        "max": max(values),
        "mean": round(sum(values) / len(values), 6),
        "start_date": observed[0][0],
        "end_date": latest_date,
        "count": len(observed),
        "observations": len(pairs),
    }
    if len(observed) > 1:
        prior = observed[-2][1]
        summary["prior"] = prior
        summary["change"] = round(latest - prior, 6)
        if prior:
            summary["pct_change"] = round((latest - prior) / abs(prior) * 100, 4)
    return summary


# --- revisions ---------------------------------------------------------------------
#
# With output_type=2 FRED returns one column per vintage, named <SERIES>_<YYYYMMDD>:
#
#     {"date": "2025-07-01", "GDPC1_20251223": "24024.957", "GDPC1_20260122": "24026.834",
#      "GDPC1_20260220": "24026.834", ... nine in total}
#
# Seven of those nine are the same number. A vintage exists for every release of the
# series, not for every change to this observation, so most columns repeat the one
# before. Collapsing them turns nine columns into "first printed as X, revised once to
# Y", which is the actual answer.


def vintage_history(row: dict, series_id: str) -> list[dict]:
    """Collapse a vintage row into the points where the value actually changed."""
    vintages: list[tuple[str, Number]] = []
    prefix = f"{series_id}_"
    for key, raw in row.items():
        if not key.startswith(prefix):
            continue
        stamp = key[len(prefix) :]
        if len(stamp) != 8 or not stamp.isdigit():
            continue
        vintages.append((f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}", parse_value(raw)))
    vintages.sort()

    history: list[dict] = []
    for vintage, value in vintages:
        if history and history[-1]["value"] == value:
            continue
        entry: dict[str, Any] = {"vintage": vintage, "value": value}
        if history:
            previous = history[-1]["value"]
            if previous is not None and value is not None:
                entry["change"] = round(value - previous, 6)
                if previous:
                    entry["pct_change"] = round((value - previous) / abs(previous) * 100, 4)
        history.append(entry)
    return history


def revision_rows(initial: list[tuple[str, Number]], current: list[tuple[str, Number]]) -> list[dict]:
    """Join first-printed against latest, one row per observation date."""
    latest = dict(current)
    rows: list[dict] = []
    for date, first in sorted(initial):
        if date not in latest:
            continue
        now = latest[date]
        row: dict[str, Any] = {"date": date, "initial": first, "current": now}
        if first is not None and now is not None:
            row["revision"] = round(now - first, 6)
            if first:
                row["revision_pct"] = round((now - first) / abs(first) * 100, 4)
        rows.append(row)
    return rows


def downsample(dates: list[str], columns: dict[str, list[Number]], max_points: int) -> tuple[list, dict, int]:
    """Thin to evenly spaced points, always keeping the first and the last.

    Returns the kept dates, the kept columns, and how many points were dropped, so a
    truncated series is never mistaken for a complete one.
    """
    total = len(dates)
    if total <= max_points:
        return dates, columns, 0

    step = (total - 1) / (max_points - 1)
    keep = sorted({round(i * step) for i in range(max_points)} | {0, total - 1})
    return (
        [dates[i] for i in keep],
        {series_id: [column[i] for i in keep] for series_id, column in columns.items()},
        total - len(keep),
    )
