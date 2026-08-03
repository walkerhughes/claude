"""Two implementations of one route matcher over one route table.

Both are expected to satisfy the same result contract: for a given path they
return `Match` objects for the routes that accept it, most specific first.
"""

import re
from dataclasses import dataclass

ROUTES: list[tuple[int, str]] = [
    (1, "/users"),
    (2, "/users/{id}"),
    (3, "/users/{id}/settings"),
    (4, "/health"),
]


@dataclass(frozen=True)
class Match:
    """One route that accepts the path, and how specific that route is."""

    route_id: int
    pattern: str
    specificity: int


def _is_parameter(segment: str) -> bool:
    return segment.startswith("{") and segment.endswith("}")


def _specificity(pattern: str) -> int:
    return sum(1 for segment in pattern.split("/") if segment and not _is_parameter(segment))


def _ranked(matches: list[Match]) -> list[Match]:
    return sorted(matches, key=lambda match: (-match.specificity, match.route_id))


def regex_router(path: str) -> list[Match]:
    """Compiled patterns: each route becomes a regex the whole path must match."""
    matches = []
    for route_id, pattern in ROUTES:
        expression = "/".join(
            "[^/]+" if _is_parameter(segment) else re.escape(segment)
            for segment in pattern.split("/")
        )
        if re.fullmatch(expression, path):
            matches.append(Match(route_id, pattern, _specificity(pattern)))
    return _ranked(matches)


def segment_router(path: str) -> list[Match]:
    """Segment walk: the path is split on / and compared one segment at a time."""
    segments = path.split("/")
    matches = []
    for route_id, pattern in ROUTES:
        expected = pattern.split("/")
        if len(expected) != len(segments):
            continue
        if all(
            (_is_parameter(want) and got) or want == got for want, got in zip(expected, segments)
        ):
            matches.append(Match(route_id, pattern, _specificity(pattern)))
    return _ranked(matches)
