import json

import pytest
from harbor.auth.errors import NotAuthenticatedError
from postgrest.exceptions import APIError

from harbor_mcp.infra.errors import error_response, guarded_tool


def test_error_response_shape():
    payload = json.loads(error_response("boom", suggestions=["fix it"], status=422))
    assert payload == {"error": "boom", "suggestions": ["fix it"], "status": 422}


def test_error_response_omits_empty_suggestions():
    assert json.loads(error_response("boom")) == {"error": "boom"}


async def test_guarded_tool_passthrough():
    @guarded_tool
    async def ok() -> str:
        return "fine"

    assert await ok() == "fine"


async def test_guarded_tool_maps_auth_error_with_suggestions():
    @guarded_tool
    async def tool() -> str:
        raise NotAuthenticatedError()

    payload = json.loads(await tool())
    assert "Not authenticated" in payload["error"]
    # The suggestions are the whole auth recovery procedure, since there is no
    # setup skill: diagnose with `harbor auth status`, then login.
    suggestions = " ".join(payload["suggestions"])
    assert "harbor auth status" in suggestions
    assert "harbor auth login" in suggestions
    # Must not send anyone back to .env; the server stopped reading it, and a
    # stale key there is what shadowed a good credentials.json once already.
    assert ".env" not in suggestions


async def test_guarded_tool_maps_postgrest_error():
    @guarded_tool
    async def tool() -> str:
        raise APIError(
            {
                "message": "no such rpc",
                "code": "PGRST202",
                "hint": None,
                "details": None,
            }
        )

    payload = json.loads(await tool())
    assert "no such rpc" in payload["error"]
    assert payload["code"] == "PGRST202"
    assert payload["suggestions"]


@pytest.mark.parametrize("exc", [ValueError("bad ref"), FileNotFoundError("task.toml not found")])
async def test_guarded_tool_maps_domain_errors_to_message(exc):
    @guarded_tool
    async def tool() -> str:
        raise exc

    assert json.loads(await tool())["error"] == str(exc)


async def test_guarded_tool_never_leaks_traceback():
    @guarded_tool
    async def tool() -> str:
        raise ZeroDivisionError("x")

    payload = json.loads(await tool())
    assert payload["error"] == "ZeroDivisionError: x"
