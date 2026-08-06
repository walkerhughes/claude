"""Integration tests drive the real tool functions against a mock FRED.

No network and no API key: the client's injected transport is the seam. Tools are
reached through the registered MCP server rather than imported directly, so the test
exercises the same path a client does, decorators and JSON rendering included.
"""

import json

import pytest
from mcp.server import MCPServer

from src import tools
from src.client import FredClient
from src.server import INSTRUCTIONS

from ..fixtures.fred_api import MockFred


@pytest.fixture
def fred() -> MockFred:
    return MockFred()


@pytest.fixture
def call(fred, monkeypatch):
    """Return an async ``call(tool_name, **kwargs)`` that returns parsed JSON."""
    tools.reset_state()
    monkeypatch.setattr(tools, "_client", FredClient(transport=fred.transport()))

    mcp = MCPServer("fred", instructions=INSTRUCTIONS)
    tools.register_all(mcp)

    async def _call(name: str, **kwargs):
        result = await mcp.call_tool(name, kwargs)
        return json.loads(_text_of(result))

    return _call


def _text_of(result: object) -> str:
    """Pull the string payload out of a CallToolResult."""
    content = getattr(result, "content", result)
    if isinstance(content, list):
        content = content[0]
    return getattr(content, "text", str(content))
