"""The server builds and its manifest matches what ships."""

import json
from pathlib import Path

import pytest

from src.server import INSTRUCTIONS, build_server, version

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


async def test_server_builds_and_exposes_its_tools():
    mcp = build_server()
    names = {tool.name for tool in await mcp.list_tools()}
    assert names == EXPECTED_TOOLS


# Grows with the stack in #30. Asserting the exact set is what catches a tool that was
# written but never registered, which is otherwise invisible until a user asks for it.
EXPECTED_TOOLS: set[str] = {
    "search_series",
    "get_series",
    "get_observations",
    "get_revisions",
    "get_release_calendar",
}


def test_instructions_name_the_entry_point():
    # A model that does not know to start with search_series will guess series IDs.
    assert "search_series" in INSTRUCTIONS


class TestPluginManifest:
    def test_mcp_json_points_at_the_launcher_that_exists(self):
        config = json.loads((ROOT / ".mcp.json").read_text())
        server = config["mcpServers"]["fred"]
        assert server["type"] == "stdio"
        script = server["args"][0].replace("${CLAUDE_PLUGIN_ROOT}/", "")
        assert (ROOT / script).exists()

    def test_the_launcher_is_executable(self):
        # Committed without the bit set, .mcp.json's "bash <script>" still works, but
        # anyone running it directly gets a permission error.
        assert (ROOT / "scripts" / "start-server.sh").stat().st_mode & 0o111

    def test_the_api_key_is_passed_through(self):
        config = json.loads((ROOT / ".mcp.json").read_text())
        assert "FRED_API_KEY" in config["mcpServers"]["fred"]["env"]

    def test_plugin_name_matches_the_server_name(self):
        manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
        config = json.loads((ROOT / ".mcp.json").read_text())
        assert manifest["name"] in config["mcpServers"]

    def test_the_server_reports_the_shipped_version(self):
        manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
        assert version() == manifest["version"]

    def test_an_unreadable_manifest_does_not_stop_the_server(self, monkeypatch, tmp_path):
        monkeypatch.setattr("src.server._MANIFEST", tmp_path / "gone.json")
        assert version() == ""
