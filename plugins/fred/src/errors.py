"""Guided error handling, modeled on Honeycomb's ``handleToolError``.

Tools never hand a traceback to the model. Every failure becomes a small JSON object:
a readable ``error`` and a ``suggestions`` list of concrete next steps. That is what
keeps a model from failing, adjusting, failing again, and giving up on the question.

FRED puts the real reason in the body rather than the status. A bad series ID and a
bad ``units`` code are both HTTP 400, and only ``error_message`` tells them apart, so
the body is what drives the suggestions here.
"""

import functools
import json
from typing import Awaitable, Callable

import httpx
from pydantic import ValidationError

from .client import CredentialsError
from .log import get_logger


def error_response(message: str, suggestions: list[str] | None = None, **extra: object) -> str:
    """Render a guided error as a JSON string (the uniform tool failure shape)."""
    payload: dict[str, object] = {"error": message}
    if suggestions:
        payload["suggestions"] = suggestions
    payload.update(extra)
    return json.dumps(payload, indent=2, default=str)


# Matched against a lowercased FRED error_message. First hit wins, so the more
# specific phrases come first.
_BODY_GUIDANCE: tuple[tuple[str, list[str]], ...] = (
    (
        "series does not exist",
        [
            "The series ID is wrong or the series has been discontinued.",
            "Find the right one with search_series, which returns IDs ordered by popularity.",
            "IDs are case-sensitive and uppercase, e.g. UNRATE, CPIAUCSL, GDPC1, DFF.",
        ],
    ),
    (
        "no vintage dates exist",
        [
            "This asks for revision history over a real-time window that has none.",
            "get_revisions sets the window itself; call it rather than passing realtime_start or realtime_end by hand.",
        ],
    ),
    (
        "frequency",
        [
            "A series can only be aggregated to a coarser frequency, never a finer one.",
            "Check the series' native frequency with get_series, then request that or coarser: d, w, bw, m, q, sa, a.",
        ],
    ),
    (
        "api_key",
        [
            "The key was rejected as malformed or unknown.",
            "Set FRED_API_KEY, or write ~/.fred-mcp/credentials.json. "
            "Ask the user to do this; never ask them to paste a key into the chat.",
        ],
    ),
    (
        "variable",
        [
            "One parameter value was rejected. The message above names it.",
            "Dates must be YYYY-MM-DD. Units must be one of lin, chg, ch1, pch, pc1, pca, cch, cca, log.",
        ],
    ),
)

_STATUS_GUIDANCE: dict[int, tuple[str, list[str]]] = {
    404: ("The endpoint was not found.", ["This is a bug in the server, not in the arguments."]),
    429: (
        "Rate limited by the FRED API (120 requests per minute).",
        [
            "Wait a few seconds and retry.",
            "Ask for several series in one get_observations call rather than one call each.",
        ],
    ),
}


def _from_http_error(exc: httpx.HTTPStatusError) -> str:
    status = exc.response.status_code
    try:
        body = exc.response.json()
    except ValueError:
        body = {}

    detail = str(body.get("error_message", "")).strip() if isinstance(body, dict) else ""
    if detail:
        # FRED double-spaces after the leading "Bad Request." sentence.
        message = " ".join(detail.split())
        lowered = message.lower()
        for needle, suggestions in _BODY_GUIDANCE:
            if needle in lowered:
                return error_response(f"FRED rejected the request: {message}", suggestions, status_code=status)
        return error_response(f"FRED rejected the request: {message}", status_code=status)

    fallback_message, suggestions = _STATUS_GUIDANCE.get(
        status, (f"The FRED API returned HTTP {status}.", ["Retry, or simplify the request."])
    )
    return error_response(fallback_message, suggestions, status_code=status)


def _from_validation_error(exc: ValidationError) -> str:
    suggestions: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()))
        msg = err.get("msg", "invalid value")
        suggestions.append(f"{loc}: {msg}" if loc else msg)
    return error_response(
        "The tool arguments did not pass validation.",
        suggestions or ["Re-read the tool docstring for the required argument shape."],
    )


def guarded_tool(func: Callable[..., Awaitable[str]]) -> Callable[..., Awaitable[str]]:
    """Wrap an async tool so any failure returns a guided error string, never a traceback."""

    @functools.wraps(func)
    async def wrapper(*args: object, **kwargs: object) -> str:
        try:
            return await func(*args, **kwargs)
        except httpx.HTTPStatusError as exc:
            get_logger().warning("http_error tool=%s status=%s", func.__name__, exc.response.status_code)
            return _from_http_error(exc)
        except ValidationError as exc:
            return _from_validation_error(exc)
        except httpx.HTTPError as exc:  # network/timeout
            return error_response(
                f"Network error contacting FRED: {type(exc).__name__}.",
                ["Check connectivity to api.stlouisfed.org.", "Retry in a moment."],
            )
        except CredentialsError as exc:
            # The message already names both locations and the signup URL, so it is
            # passed through verbatim.
            get_logger().warning("credentials_error tool=%s", func.__name__)
            return error_response(str(exc), ["See the fred plugin README for setup."])
        except (KeyError, ValueError, TypeError) as exc:
            get_logger().warning("tool_value_error tool=%s err=%s", func.__name__, exc)
            return error_response(f"Could not process the request: {exc}", ["Re-check the arguments and retry."])
        except Exception as exc:  # noqa: BLE001
            # Last resort. Without this the docstring's promise is false: anything
            # outside the cases above reaches the client as a raw traceback.
            get_logger().exception("unexpected_error tool=%s", func.__name__)
            return error_response(f"{type(exc).__name__}: {exc}")

    return wrapper
