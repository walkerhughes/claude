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
