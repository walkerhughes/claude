"""FRED API client: key resolution, request signing, and retry.

The API is read-only and authenticates with a single key, so there is no token
refresh and no write path to gate. What is left is worth doing carefully: resolving
the key from two places with a message that helps when it is in neither, and backing
off rather than failing when the 120-requests-per-minute limit is hit.
"""

import asyncio
import json
import os
import re
import time
from pathlib import Path

import httpx

from .log import get_logger

DEFAULT_BASE_URL = "https://api.stlouisfed.org/fred"
CREDENTIALS_PATH = Path.home() / ".fred-mcp" / "credentials.json"

# FRED rejects anything else with an unhelpful message about variable api_key, so
# the shape is checked locally to name the real problem.
_KEY_PATTERN = re.compile(r"^[a-z0-9]{32}$")

_MISSING_KEY = (
    "No FRED API key found. Set FRED_API_KEY in the environment, or write "
    f'{CREDENTIALS_PATH} containing {{"api_key": "<your key>"}}. '
    "A key is free at https://fredaccount.stlouisfed.org/apikeys."
)

# Retried statuses. 429 is the documented rate limit; the 5xx set covers the
# upstream blipping. Anything else (notably 400) is the caller's problem.
_RETRY_STATUSES = (429, 500, 502, 503, 504)
_BACKOFFS = (0.5, 1.0, 2.0)


class CredentialsError(RuntimeError):
    """The API key is missing or malformed. Message is shown to the model verbatim."""


def resolve_api_key() -> str:
    """Return the API key from the environment, else the credentials file.

    Raises CredentialsError naming both locations when neither has one. The key is
    never included in any message raised from here.
    """
    env_key = (os.environ.get("FRED_API_KEY") or "").strip()
    if env_key:
        return _validated(env_key, "FRED_API_KEY")

    if CREDENTIALS_PATH.exists():
        try:
            data = json.loads(CREDENTIALS_PATH.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise CredentialsError(f"{CREDENTIALS_PATH} could not be read as JSON: {exc}") from exc
        file_key = str(data.get("api_key") or "").strip()
        if file_key:
            return _validated(file_key, str(CREDENTIALS_PATH))
        raise CredentialsError(f'{CREDENTIALS_PATH} has no "api_key" field. {_MISSING_KEY}')

    raise CredentialsError(_MISSING_KEY)


def _validated(key: str, source: str) -> str:
    if not _KEY_PATTERN.match(key):
        raise CredentialsError(
            f"The FRED API key from {source} is not in the expected form "
            "(32 lowercase alphanumeric characters). Check it for stray whitespace, "
            "quotes, or capitals, and re-copy it from "
            "https://fredaccount.stlouisfed.org/apikeys."
        )
    return key


def _clean_params(params: dict) -> dict:
    """Drop unset params and render the rest the way FRED expects.

    None and "" mean "not set" throughout the tool layer, so they are dropped here
    rather than sent as empty values, which FRED rejects.
    """
    out: dict[str, str] = {}
    for key, value in params.items():
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            out[key] = "true" if value else "false"
        elif isinstance(value, (list, tuple)):
            if not value:
                continue
            out[key] = ",".join(str(v) for v in value)
        else:
            out[key] = str(value)
    return out


class FredClient:
    """Async client for https://api.stlouisfed.org/fred."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # Resolved lazily so that constructing a client (which happens at import time
        # in the tool layer) never raises; a missing key should surface as a guided
        # error from the tool that needed it, not as a server that will not start.
        self._api_key = api_key
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._transport = transport
        self._http: httpx.AsyncClient | None = None

    def api_key(self) -> str:
        if not self._api_key:
            self._api_key = resolve_api_key()
        return self._api_key

    async def _http_client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"Accept": "application/json", "User-Agent": "fred-mcp/0.1"},
                timeout=30.0,
                transport=self._transport,
            )
        return self._http

    async def get(self, path: str, **params: object) -> dict:
        """GET a FRED endpoint with the key and file_type injected.

        Retries 429 and 5xx with backoff, then raises for status so the caller's
        @guarded_tool can turn the response body into guided suggestions.
        """
        query = _clean_params(params)
        query["api_key"] = self.api_key()
        query["file_type"] = "json"

        http = await self._http_client()
        log = get_logger()

        for attempt in range(len(_BACKOFFS) + 1):
            start = time.monotonic()
            resp = await http.get(path, params=query)
            dur_ms = round((time.monotonic() - start) * 1000, 1)
            log.debug("api_request path=%s status=%s ms=%s", path, resp.status_code, dur_ms)

            if resp.status_code in _RETRY_STATUSES and attempt < len(_BACKOFFS):
                delay = _BACKOFFS[attempt]
                log.warning("api_retry path=%s status=%s attempt=%s delay=%s", path, resp.status_code, attempt, delay)
                await asyncio.sleep(delay)
                continue
            break

        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        if self._http and not self._http.is_closed:
            await self._http.aclose()
