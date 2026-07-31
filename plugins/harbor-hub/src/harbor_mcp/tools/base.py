"""Shared helpers for tools: compact model-facing JSON and write gating."""

import json
import os
from typing import Any


def fmt(data: Any) -> str:
    """Compact JSON for the model: no whitespace, non-JSON types via str()."""
    return json.dumps(data, default=str, separators=(",", ":"))


def compact(data: dict[str, Any]) -> dict[str, Any]:
    """Drop None values so payloads stay small; falsy ints/strs/lists survive."""
    return {k: v for k, v in data.items() if v is not None}


def truncate(items: list[Any], limit: int) -> tuple[list[Any], str | None]:
    """Cap a list, returning (items, note). The note tells the model data was cut."""
    if limit <= 0 or len(items) <= limit:
        return items, None
    return (
        items[:limit],
        f"showing {limit} of {len(items)} items; pass a larger limit or paginate for the rest",
    )


def writes_enabled() -> bool:
    return os.environ.get("HARBOR_MCP_ENABLE_WRITES", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
