"""Error handling for MCP tools: the model gets recovery guidance, never a traceback."""

import functools
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from harbor.auth.errors import AuthenticationError
from postgrest.exceptions import APIError
from storage3.exceptions import StorageApiError

logger = logging.getLogger(__name__)

# The whole auth recovery procedure lives here rather than in a skill: it costs
# nothing until auth actually fails, which is the only moment it is useful.
AUTH_SUGGESTIONS = [
    "Run `harbor auth status` in a terminal to see whether a credential is "
    "stored. It exits 0 either way, so read its output, not its exit code.",
    "If it reports `Not authenticated`, ask the user to run `harbor auth login` "
    "themselves; it is an interactive OAuth flow and stores a key scoped to "
    "them in ~/.harbor/credentials.json.",
    "If it reports a logged-in user, the stored key is revoked or expired: ask "
    "the user to run `harbor auth logout` and then `harbor auth login` again.",
    "The server must be restarted to pick up new credentials. Then call whoami "
    "to confirm.",
]


def error_response(
    message: str, suggestions: list[str] | None = None, **extra: Any
) -> str:
    payload: dict[str, Any] = {"error": message}
    if suggestions:
        payload["suggestions"] = suggestions
    payload.update(extra)
    return json.dumps(payload, default=str)


def guarded_tool(func: Callable[..., Awaitable[str]]) -> Callable[..., Awaitable[str]]:
    """Wrap an async tool so every failure becomes an actionable JSON payload."""

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> str:
        try:
            return await func(*args, **kwargs)
        except AuthenticationError as exc:
            return error_response(str(exc), suggestions=AUTH_SUGGESTIONS)
        except APIError as exc:
            logger.debug("postgrest error in %s", func.__name__, exc_info=True)
            return error_response(
                f"Harbor hub query failed: {exc.message}",
                suggestions=[
                    "Check the id/org/name arguments exist and are spelled correctly.",
                    "Rows hidden by permissions look identical to missing rows; "
                    "confirm the resource belongs to your account.",
                ],
                code=exc.code,
            )
        except StorageApiError as exc:
            logger.debug("storage error in %s", func.__name__, exc_info=True)
            return error_response(
                f"Harbor hub storage operation failed: {exc.message}",
                suggestions=[
                    "Retry once; if it persists, verify the archive exists via check_job_upload."
                ],
                status=exc.status,
            )
        except (ValueError, FileNotFoundError, RuntimeError, PermissionError) as exc:
            return error_response(str(exc))
        except Exception as exc:  # noqa: BLE001 - last resort: never leak a traceback
            logger.exception("unexpected error in %s", func.__name__)
            return error_response(f"{type(exc).__name__}: {exc}")

    return wrapper
