"""Every failure a tool can hit becomes {error, suggestions}, never a traceback."""

import json

import httpx
import pytest
from pydantic import BaseModel, ValidationError

from src.client import CredentialsError
from src.errors import guarded_tool

pytestmark = pytest.mark.unit


def http_error(status: int, body: object) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://api.stlouisfed.org/fred/series")
    response = httpx.Response(status, json=body, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


async def run_raising(exc: Exception) -> dict:
    @guarded_tool
    async def tool() -> str:
        raise exc

    return json.loads(await tool())


class TestFredBodyGuidance:
    async def test_missing_series_points_at_search_series(self):
        body = {"error_code": 400, "error_message": "Bad Request.  The series does not exist."}
        result = await run_raising(http_error(400, body))
        assert "The series does not exist" in result["error"]
        assert any("search_series" in s for s in result["suggestions"])
        assert result["status_code"] == 400

    async def test_the_doubled_space_in_fred_messages_is_normalized(self):
        body = {"error_code": 400, "error_message": "Bad Request.  The series does not exist."}
        result = await run_raising(http_error(400, body))
        assert "Request.  The" not in result["error"]

    async def test_missing_vintages_points_at_get_revisions(self):
        body = {
            "error_code": 400,
            "error_message": "Bad Request.  No vintage dates exist for the specified real-time period.",
        }
        result = await run_raising(http_error(400, body))
        assert any("get_revisions" in s for s in result["suggestions"])

    async def test_frequency_error_explains_the_coarser_only_rule(self):
        body = {
            "error_code": 400,
            "error_message": "Bad Request.  The frequency is not lower or equal to the series frequency.",
        }
        result = await run_raising(http_error(400, body))
        assert any("coarser" in s for s in result["suggestions"])

    async def test_rejected_key_never_asks_the_user_to_paste_it(self):
        body = {"error_code": 400, "error_message": "Bad Request.  The value for variable api_key is not valid."}
        result = await run_raising(http_error(400, body))
        assert any("never ask them to paste" in s.lower() for s in result["suggestions"])

    async def test_unrecognized_body_still_surfaces_the_message(self):
        body = {"error_code": 400, "error_message": "Bad Request.  Something entirely new."}
        result = await run_raising(http_error(400, body))
        assert "Something entirely new" in result["error"]


class TestStatusFallback:
    async def test_429_without_a_body(self):
        result = await run_raising(http_error(429, {}))
        assert "Rate limited" in result["error"]
        assert any("one get_observations call" in s for s in result["suggestions"])

    async def test_unmapped_status(self):
        result = await run_raising(http_error(503, {}))
        assert "HTTP 503" in result["error"]

    async def test_non_json_body(self):
        request = httpx.Request("GET", "https://api.stlouisfed.org/fred/series")
        response = httpx.Response(500, text="<html>gateway</html>", request=request)
        result = await run_raising(httpx.HTTPStatusError("boom", request=request, response=response))
        assert "HTTP 500" in result["error"]


class TestOtherFailures:
    async def test_validation_error_lists_each_field(self):
        class Args(BaseModel):
            limit: int

        try:
            Args(limit="not a number")
        except ValidationError as exc:
            captured = exc
        result = await run_raising(captured)
        assert result["error"].startswith("The tool arguments did not pass validation")
        assert any(s.startswith("limit:") for s in result["suggestions"])

    async def test_network_error(self):
        result = await run_raising(httpx.ConnectTimeout("timed out"))
        assert "Network error" in result["error"]

    async def test_credentials_error_passes_the_message_through(self):
        result = await run_raising(CredentialsError("No FRED API key found. Set FRED_API_KEY."))
        assert result["error"] == "No FRED API key found. Set FRED_API_KEY."

    async def test_an_unexpected_exception_does_not_escape(self):
        # The whole promise of @guarded_tool: nothing reaches the model as a traceback.
        result = await run_raising(RuntimeError("something nobody anticipated"))
        assert result["error"] == "RuntimeError: something nobody anticipated"

    async def test_a_successful_tool_is_untouched(self):
        @guarded_tool
        async def tool() -> str:
            return '{"ok": true}'

        assert await tool() == '{"ok": true}'
