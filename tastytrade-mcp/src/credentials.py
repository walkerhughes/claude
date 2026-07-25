"""OAuth credential resolution for the Tastytrade MCP server.

Credentials come from exactly one of two sources, in precedence order:

1. ``TT_CLIENT_ID`` / ``TT_SECRET`` / ``TT_REFRESH`` in the environment, for CI
   and scripting.
2. ``~/.tastytrade-mcp/credentials.json``, for interactive use.

Whole-source rather than per-field: a file ``client_id`` paired with an
environment ``refresh_token`` would fail authentication in a way that looks like
a revoked token rather than a configuration mistake. A *partially* set
environment is treated as an error instead of silently falling through to the
file, because that fallthrough is invisible and the resulting 401 is misleading.

Unlike harbor, Tastytrade has no `auth login` command to write this file. The
values come from a registered OAuth application, so the file is created by hand;
see the README.
"""

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

CREDENTIALS_PATH = Path.home() / ".tastytrade-mcp" / "credentials.json"

DEFAULT_BASE_URL = "api.tastyworks.com"

# JSON key -> environment variable holding the same value.
ENV_VARS = {
    "client_id": "TT_CLIENT_ID",
    "client_secret": "TT_SECRET",
    "refresh_token": "TT_REFRESH",
}


class CredentialsError(RuntimeError):
    """Raised when no usable credential set can be resolved."""


@dataclass(frozen=True)
class Credentials:
    """A resolved credential set, plus where it came from (never the secret)."""

    client_id: str
    client_secret: str
    refresh_token: str
    base_url: str
    source: str  # "env" or the credentials file path


def _read_file(path: Path) -> dict[str, str]:
    """Return the parsed credentials file, or {} when it does not exist.

    Refuses a file that is readable by group or others. It carries an OAuth
    client secret and a refresh token, which together grant full account access
    including order placement when trading is enabled.
    """
    try:
        mode = path.stat().st_mode
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise CredentialsError(f"Could not read {path}: {exc}") from exc

    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise CredentialsError(
            f"{path} is accessible to other users (mode {stat.filemode(mode)}). "
            f"It holds an OAuth secret and refresh token. Run: chmod 600 {path}"
        )

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise CredentialsError(f"Could not read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CredentialsError(f"{path} is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise CredentialsError(f"{path} must contain a JSON object, got {type(data).__name__}.")
    return {k: v for k, v in data.items() if isinstance(v, str) and v.strip()}


def resolve_credentials(path: Path | None = None) -> Credentials:
    """Resolve credentials from the environment, else the credentials file."""
    path = path or CREDENTIALS_PATH

    present = {field: os.environ.get(var, "").strip() for field, var in ENV_VARS.items()}
    set_fields = {f for f, v in present.items() if v}

    if set_fields == set(ENV_VARS):
        return Credentials(
            **present,
            base_url=os.environ.get("API_BASE_URL", "").strip() or DEFAULT_BASE_URL,
            source="env",
        )

    if set_fields:
        missing = sorted(ENV_VARS[f] for f in ENV_VARS if f not in set_fields)
        raise CredentialsError(
            f"Incomplete credentials in the environment: {', '.join(missing)} "
            f"not set. Set all three, or unset them all to use {path} instead."
        )

    data = _read_file(path)
    if not data:
        raise CredentialsError(
            f"No Tastytrade credentials found. Create {path} containing "
            '{"client_id": "...", "client_secret": "...", "refresh_token": "..."} '
            "with mode 600, or set TT_CLIENT_ID, TT_SECRET and TT_REFRESH."
        )

    missing = sorted(set(ENV_VARS) - set(data))
    if missing:
        raise CredentialsError(f"{path} is missing required key(s): {', '.join(missing)}.")

    return Credentials(
        client_id=data["client_id"],
        client_secret=data["client_secret"],
        refresh_token=data["refresh_token"],
        base_url=data.get("base_url", "").strip() or os.environ.get("API_BASE_URL", "").strip() or DEFAULT_BASE_URL,
        source=str(path),
    )
