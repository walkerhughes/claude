"""The server builds and its manifest matches what ships."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from src.client import _KEY_PATTERN
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


class TestAuthCommand:
    """The /fred:auth command and the script behind it.

    The invariant worth pinning is that the command never collects the key itself. A
    key pasted into the conversation is in the transcript and in the context window,
    neither of which the user can rotate away, so the command delegates to a script
    that prompts through the OS instead.
    """

    COMMAND = ROOT / "commands" / "auth.md"
    SCRIPT = ROOT / "scripts" / "save-credentials.sh"

    def test_the_command_exists_with_a_description(self):
        text = self.COMMAND.read_text()
        assert text.startswith("---")
        front = text.split("---")[1]
        assert "description:" in front
        assert "~/.fred-mcp/credentials.json" in front

    def test_the_command_runs_the_script_that_exists(self):
        assert self.SCRIPT.exists()
        assert os.access(self.SCRIPT, os.X_OK), "the helper must be executable"
        assert "scripts/save-credentials.sh" in self.COMMAND.read_text()

    def test_the_command_forbids_collecting_the_key_in_chat(self):
        text = self.COMMAND.read_text().lower()
        assert "do not ask the user to type or paste their api key" in text

    def test_the_script_never_prints_the_key(self, tmp_path):
        """Run the rejection path and confirm the key is nowhere in the output.

        stdout is read by the agent, so a diagnostic that helpfully echoed what was
        pasted would defeat the whole design. A malformed key is rejected locally, so
        this needs no network.
        """
        secret = "THIS-IS-THE-SECRET-VALUE-NOT-A-KEY"
        result = subprocess.run(
            ["bash", str(self.SCRIPT)],
            input=secret,
            capture_output=True,
            text=True,
            env={**os.environ, "FRED_CRED_DIR": str(tmp_path), "FRED_API_KEY_STDIN": "1"},
        )
        assert result.returncode == 1
        assert secret not in result.stdout + result.stderr
        assert not (tmp_path / "credentials.json").exists()

    def test_no_echo_of_the_key_anywhere_in_the_script(self):
        """The static half: the key reaches the file and nothing else."""
        for line in self.SCRIPT.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "$key" not in stripped:
                continue
            if stripped.startswith(("echo", "printf")):
                assert stripped.endswith('> "$CRED_FILE"'), f"key must not reach the terminal: {stripped}"

    def test_the_script_validator_agrees_with_the_client(self):
        """One rule for a well-formed key, checked in two places.

        The script rejects a bad paste at the prompt; client.py rejects it at call
        time. If they drifted apart, /fred:auth would happily save a key the server
        then refuses.
        """
        assert "^[a-z0-9]{32}$" in self.SCRIPT.read_text()
        assert _KEY_PATTERN.pattern == "^[a-z0-9]{32}$"

    def test_the_script_selftest_passes(self):
        result = subprocess.run(["bash", str(self.SCRIPT), "--selftest"], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_writing_is_the_last_step_after_verification(self):
        """A mistyped key during a rotation must not overwrite a working one."""
        body = self.SCRIPT.read_text()
        assert body.index("FRED rejected that key") < body.index('> "$CRED_FILE"')


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

    def test_every_setting_the_server_reads_is_passed_through(self):
        """An env var the code honours but .mcp.json drops does nothing once installed.

        FRED_BASE_URL was documented in .env.example, unread by the code, and absent
        here; two of those three were fixed together, so this pins the third.
        """
        config = json.loads((ROOT / ".mcp.json").read_text())
        assert set(config["mcpServers"]["fred"]["env"]) == {"FRED_API_KEY", "FRED_BASE_URL", "FRED_LOG_LEVEL"}

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

    def test_the_plugin_root_placeholder_has_no_default_fallback(self):
        """``${CLAUDE_PLUGIN_ROOT:-.}`` silently expands to ``.``, not the plugin root.

        The ``:-default`` form is handled by env-var expansion, which does not know
        CLAUDE_PLUGIN_ROOT, so the default always wins and the server launches against
        the user's own project directory. Only the bare form is substituted by the
        plugin loader. This has shipped broken in this repo before.
        """
        config = json.loads((ROOT / ".mcp.json").read_text())
        for arg in config["mcpServers"]["fred"]["args"]:
            assert ":-" not in arg, f"{arg!r} uses a :-default; CLAUDE_PLUGIN_ROOT must be bare"

    def test_the_config_never_names_a_secret_value(self):
        raw = (ROOT / ".mcp.json").read_text()
        assert "source .env" not in raw
        # The key is passed through by name only; a literal here would be committed.
        assert raw.count("FRED_API_KEY") == 2  # the key and its ${...} reference


class TestMarketplace:
    """The plugin is only installable once it is listed, and only correct if the
    listing points at the directory the manifest actually lives in."""

    MARKETPLACE = ROOT.parents[1] / ".claude-plugin" / "marketplace.json"

    def entry(self) -> dict:
        plugins = json.loads(self.MARKETPLACE.read_text())["plugins"]
        matches = [p for p in plugins if p["name"] == "fred"]
        assert matches, "fred is not listed in the marketplace, so it cannot be installed"
        return matches[0]

    def test_the_source_path_resolves_to_this_plugin(self):
        source = (self.MARKETPLACE.parent.parent / self.entry()["source"]).resolve()
        assert source == ROOT

    def test_the_listing_has_a_description(self):
        assert len(self.entry().get("description", "")) > 40
