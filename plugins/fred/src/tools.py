"""MCP tools. Each is registered on the FastMCP server by ``register_all``.

Tools are added over the stack in #30; this module is the seam they attach to.
"""

import json

from mcp.server import MCPServer

from .client import FredClient

_client: FredClient | None = None


def get_client() -> FredClient:
    """Lazy-init the API client so the key is read at tool time, not import time."""
    global _client
    if _client is None:
        _client = FredClient()
    return _client


def reset_state() -> None:
    """Test hook: drop the client singleton."""
    global _client
    _client = None


def fmt(data: object) -> str:
    """Render a tool result as compact, stable JSON."""
    return json.dumps(data, indent=2, default=str)


def register_all(mcp: MCPServer) -> None:
    """Register every tool on the given MCP server."""
