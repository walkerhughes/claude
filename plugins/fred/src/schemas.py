"""Argument schemas: correct first, then validate.

Two jobs, in the order that matters. A ``model_validator(mode="before")`` rewrites the
arguments a model plausibly writes into the ones FRED accepts, and a
``mode="after"`` validator rejects what is left with a message that names the fix.

Correction is not politeness. FRED's vocabulary is not guessable: series IDs are
case-sensitive and uppercase, frequencies are single letters. A model that writes
``frequency="monthly"`` and gets a 400 will retry with something worse, and two rounds
later it has simplified the question into one it can answer badly.
"""

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from . import dates

MAX_SERIES_PER_CALL = 20

# FRED's frequency codes, and the words a model writes instead.
FREQUENCY_ALIASES: dict[str, str] = {
    "d": "d", "daily": "d", "day": "d",
    "w": "w", "weekly": "w", "week": "w",
    "bw": "bw", "biweekly": "bw", "bi-weekly": "bw", "biweek": "bw",
    "m": "m", "monthly": "m", "month": "m", "mo": "m",
    "q": "q", "quarterly": "q", "quarter": "q",
    "sa": "sa", "semiannual": "sa", "semiannually": "sa", "semi-annual": "sa", "biannual": "sa",
    "a": "a", "annual": "a", "annually": "a", "yearly": "a", "year": "a", "y": "a",
}  # fmt: skip

# Both filters are applied as FRED tags rather than as filter_variable/filter_value.
# A request carries exactly one filter_variable, so filtering on frequency *and*
# seasonal adjustment that way means doing one of them locally, over a page FRED
# already truncated, against a count that no longer means anything. tag_names takes
# several at once, server-side, and the count stays true.
#
# These are FRED's own tag names, from /fred/tags?tag_group_id=freq and =seas.
FREQUENCY_TAGS: dict[str, str] = {
    "d": "daily",
    "w": "weekly",
    "bw": "biweekly",
    "m": "monthly",
    "q": "quarterly",
    "sa": "semiannual",
    "a": "annual",
}

# The seas group holds only these two. Series marked SAAR carry the "sa" tag, so
# "saar" resolves there rather than to a tag that does not exist.
SEASONAL_TAGS: dict[str, str] = {
    "sa": "sa",
    "seasonally adjusted": "sa",
    "seasonal": "sa",
    "adjusted": "sa",
    "saar": "sa",
    "seasonally adjusted annual rate": "sa",
    "nsa": "nsa",
    "not seasonally adjusted": "nsa",
    "unadjusted": "nsa",
    "raw": "nsa",
}

SERIES_ORDER_BY = {
    "popularity",
    "group_popularity",
    "search_rank",
    "series_id",
    "title",
    "units",
    "frequency",
    "seasonal_adjustment",
    "last_updated",
    "observation_start",
    "observation_end",
}

SERIES_INCLUDES = ("metadata", "notes", "release", "categories", "tags")

# What each FRED units code actually does, echoed in the response so the numbers are
# not left to be guessed at.
UNITS_MEANING: dict[str, str] = {
    "lin": "levels, as published",
    "chg": "change from the previous period",
    "ch1": "change from a year ago",
    "pch": "percent change from the previous period",
    "pc1": "percent change from a year ago",
    "pca": "compounded annual rate of change",
    "cch": "continuously compounded rate of change",
    "cca": "continuously compounded annual rate of change",
    "log": "natural log",
}

# The single highest-value table in this file. "Year over year percent change" is the
# most-asked transformation in all of economics and FRED spells it "pc1".
UNITS_ALIASES: dict[str, str] = {
    "": "lin", "lin": "lin", "level": "lin", "levels": "lin", "none": "lin",
    "raw": "lin", "as published": "lin", "nominal": "lin",
    "pc1": "pc1", "yoy": "pc1", "y/y": "pc1", "yoy%": "pc1", "year over year": "pc1",
    "year-over-year": "pc1", "annual percent change": "pc1", "percent change from year ago": "pc1",
    "percent change from a year ago": "pc1", "inflation": "pc1",
    "pch": "pch", "mom": "pch", "m/m": "pch", "month over month": "pch",
    "percent change": "pch", "pct change": "pch", "pct_change": "pch",
    "percent change from previous period": "pch",
    "chg": "chg", "change": "chg", "diff": "chg", "difference": "chg",
    "change from previous period": "chg",
    "ch1": "ch1", "change from year ago": "ch1", "change from a year ago": "ch1",
    "pca": "pca", "annualized": "pca", "saar": "pca", "annual rate": "pca",
    "compounded annual rate of change": "pca",
    "cch": "cch", "cca": "cca", "log": "log", "natural log": "log", "ln": "log",
}  # fmt: skip

AGGREGATION_ALIASES: dict[str, str] = {
    "avg": "avg", "average": "avg", "mean": "avg",
    "sum": "sum", "total": "sum",
    "eop": "eop", "end": "eop", "end of period": "eop", "last": "eop", "close": "eop",
}  # fmt: skip


def normalize_series_ids(value: Any) -> Any:
    """Accept the several ways a model writes a list of series IDs.

    ``"unrate"``, ``"UNRATE, CPIAUCSL"``, ``"UNRATE CPIAUCSL"`` and ``["unrate"]`` all
    become ``["UNRATE", ...]``. FRED IDs are uppercase and it will not meet you halfway.
    Order is preserved and duplicates are dropped, so asking for the same series twice
    does not fetch it twice.
    """
    if isinstance(value, str):
        value = value.replace(",", " ").split()
    if not isinstance(value, (list, tuple)):
        return value

    seen: dict[str, None] = {}
    for item in value:
        if not isinstance(item, str):
            return value  # let pydantic report the real type error
        for part in item.replace(",", " ").split():
            seen.setdefault(part.strip().upper(), None)
    return list(seen)


def normalize_frequency(value: Any) -> Any:
    if isinstance(value, str) and value.strip():
        return FREQUENCY_ALIASES.get(value.strip().lower(), value.strip())
    return value


def normalize_seasonal(value: Any) -> Any:
    if isinstance(value, str) and value.strip():
        return SEASONAL_TAGS.get(value.strip().lower(), value.strip())
    return value


def _as_list(value: Any) -> Any:
    """A model asked for a list often sends a bare string or a comma-joined one."""
    if isinstance(value, str):
        return [part.strip() for part in value.replace(",", " ").split() if part.strip()]
    return value


class SearchArgs(BaseModel):
    """Arguments for search_series: one of three discovery paths, one output shape."""

    query: str = ""
    release_id: int | None = None
    category_id: int | None = None
    limit: int = Field(default=10, ge=1, le=100)
    frequency: str = ""
    seasonal_adjustment: str = ""
    order_by: str = "popularity"

    @model_validator(mode="before")
    @classmethod
    def _correct(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if "frequency" in data:
            data["frequency"] = normalize_frequency(data["frequency"])
        if "seasonal_adjustment" in data:
            data["seasonal_adjustment"] = normalize_seasonal(data["seasonal_adjustment"])
        if isinstance(data.get("order_by"), str):
            data["order_by"] = data["order_by"].strip().lower().replace(" ", "_") or "popularity"
        if isinstance(data.get("query"), str):
            data["query"] = data["query"].strip()
        return data

    @field_validator("frequency")
    @classmethod
    def _known_frequency(cls, value: str) -> str:
        if value and value not in FREQUENCY_TAGS:
            raise ValueError(f"unknown frequency {value!r}; use one of {', '.join(FREQUENCY_TAGS)}")
        return value

    @field_validator("seasonal_adjustment")
    @classmethod
    def _known_seasonal(cls, value: str) -> str:
        if value and value not in ("sa", "nsa"):
            raise ValueError(f"unknown seasonal_adjustment {value!r}; use 'SA', 'NSA', or 'unadjusted'")
        return value

    @field_validator("order_by")
    @classmethod
    def _known_order_by(cls, value: str) -> str:
        if value not in SERIES_ORDER_BY:
            raise ValueError(f"unknown order_by {value!r}; use one of {', '.join(sorted(SERIES_ORDER_BY))}")
        return value

    @model_validator(mode="after")
    def _exactly_one_path(self) -> "SearchArgs":
        paths = (("query", self.query), ("release_id", self.release_id), ("category_id", self.category_id))
        chosen = [name for name, value in paths if value not in ("", None)]
        if not chosen:
            raise ValueError(
                "supply one of query (free-text search), release_id (every series in a "
                "release), or category_id (every series in a category)"
            )
        if len(chosen) > 1:
            raise ValueError(f"supply only one of query, release_id, category_id; got {' and '.join(chosen)}")
        return self

    @property
    def tag_names(self) -> str:
        """The filters as FRED's semicolon-joined tag list, empty when none are set."""
        tags = [FREQUENCY_TAGS[self.frequency]] if self.frequency else []
        if self.seasonal_adjustment:
            tags.append(self.seasonal_adjustment)
        return ";".join(tags)

    @property
    def path(self) -> str:
        if self.query:
            return "/series/search"
        if self.release_id is not None:
            return "/release/series"
        return "/category/series"


class GetSeriesArgs(BaseModel):
    """Arguments for get_series."""

    series_ids: list[str] = Field(min_length=1, max_length=MAX_SERIES_PER_CALL)
    include: list[str] = Field(default_factory=lambda: ["metadata"])

    @model_validator(mode="before")
    @classmethod
    def _correct(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if "series_ids" in data:
            data["series_ids"] = normalize_series_ids(data["series_ids"])
        if "include" in data and data["include"] is not None:
            include = _as_list(data["include"])
            if isinstance(include, list):
                lowered = [str(part).strip().lower() for part in include]
                if "all" in lowered:
                    lowered = list(SERIES_INCLUDES)
                data["include"] = lowered
        return data

    @field_validator("include")
    @classmethod
    def _known_includes(cls, value: list[str]) -> list[str]:
        unknown = [part for part in value if part not in SERIES_INCLUDES]
        if unknown:
            raise ValueError(
                f"unknown include {', '.join(repr(u) for u in unknown)}; "
                f"use any of {', '.join(SERIES_INCLUDES)}, or 'all'"
            )
        return value

    def wants(self, part: str) -> bool:
        return part in self.include


class ObservationArgs(BaseModel):
    """Arguments for get_observations."""

    series_ids: list[str] = Field(min_length=1, max_length=MAX_SERIES_PER_CALL)
    start: str = ""
    end: str = ""
    units: str = "lin"
    frequency: str = ""
    aggregation_method: str = "avg"
    # Floor of 2 because downsampling always keeps the first and last point; a cap of
    # one cannot express a series.
    max_points: int = Field(default=120, ge=2, le=2000)

    @model_validator(mode="before")
    @classmethod
    def _correct(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if "series_ids" in data:
            data["series_ids"] = normalize_series_ids(data["series_ids"])
        for field in ("start", "end"):
            if data.get(field) is not None:
                data[field] = dates.parse(data[field], field=field)
        if data.get("units") is not None:
            raw = str(data["units"]).strip().lower()
            data["units"] = UNITS_ALIASES.get(raw, raw)
        if "frequency" in data:
            data["frequency"] = normalize_frequency(data["frequency"])
        if data.get("aggregation_method") is not None:
            raw = str(data["aggregation_method"]).strip().lower()
            data["aggregation_method"] = AGGREGATION_ALIASES.get(raw, raw)
        return data

    @field_validator("units")
    @classmethod
    def _known_units(cls, value: str) -> str:
        if value not in UNITS_MEANING:
            raise ValueError(
                f"unknown units {value!r}; use a FRED code ({', '.join(UNITS_MEANING)}) "
                "or a phrase such as 'yoy', 'percent change', 'level'"
            )
        return value

    @field_validator("frequency")
    @classmethod
    def _known_frequency(cls, value: str) -> str:
        if value and value not in FREQUENCY_TAGS:
            raise ValueError(f"unknown frequency {value!r}; use one of {', '.join(FREQUENCY_TAGS)}")
        return value

    @field_validator("aggregation_method")
    @classmethod
    def _known_aggregation(cls, value: str) -> str:
        if value not in ("avg", "sum", "eop"):
            raise ValueError(f"unknown aggregation_method {value!r}; use avg, sum, or eop")
        return value

    @model_validator(mode="after")
    def _range_is_the_right_way_round(self) -> "ObservationArgs":
        if self.start and self.end and self.start > self.end:
            raise ValueError(f"start ({self.start}) is after end ({self.end}); swap them")
        return self

    @property
    def units_meaning(self) -> str:
        return UNITS_MEANING[self.units]
