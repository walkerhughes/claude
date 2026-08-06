"""FRED MCP server.

Task-oriented tools built for a model rather than one wrapper per REST endpoint. See
docs/design.md for the reasoning.

Tool surface:
  Discovery:  search_series, get_series
  Data:       get_observations
  Revisions:  get_revisions
  Schedule:   get_release_calendar
"""

import json
from pathlib import Path

from mcp.server import MCPServer

from .log import configure_logging
from .tools import register_all

_MANIFEST = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"

INSTRUCTIONS = (
    "Economic data from FRED (Federal Reserve Bank of St. Louis). Series are named by "
    "opaque IDs, so start with search_series unless you already know the ID; it orders "
    "by popularity, so the canonical series comes first. get_series explains what a "
    "series measures, in what units, and how current it is. get_observations is the "
    "workhorse: pass several series IDs at once to get them aligned on one date index, "
    "and use units='yoy' for year-over-year percent change rather than doing the "
    "arithmetic yourself. get_revisions answers what a number was first reported as. "
    "get_release_calendar shows what data just came out and what is scheduled next."
)


def version() -> str:
    """Read the shipped version from the plugin manifest.

    Hardcoding it here would drift from plugin.json, which the repo's plugin-version
    workflow requires be bumped on every change. One source, so it cannot.
    """
    try:
        return str(json.loads(_MANIFEST.read_text())["version"])
    except (OSError, ValueError, KeyError):
        return ""


def build_server() -> MCPServer:
    """Construct and configure the MCP server with all tools."""
    configure_logging()
    mcp = MCPServer("fred", instructions=INSTRUCTIONS, version=version())
    register_all(mcp)
    return mcp


mcp = build_server()


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
