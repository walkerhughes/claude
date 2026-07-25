"""Guards on the shipped plugin config.

A bad .mcp.json fails at MCP connect time with an opaque -32000 that no other
test can see. The harbor-mcp plugin shipped broken three times before these
checks existed, so they are duplicated here rather than shared.
"""

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
MCP_CONFIG = REPO / ".mcp.json"
PLUGIN_MANIFEST = REPO / ".claude-plugin" / "plugin.json"


def server_config() -> dict:
    servers = json.loads(MCP_CONFIG.read_text())["mcpServers"]
    assert len(servers) == 1, f"expected one server, got {list(servers)}"
    return next(iter(servers.values()))


def test_plugin_root_has_no_default_fallback():
    """`${CLAUDE_PLUGIN_ROOT:-.}` silently expands to `.`, not the plugin root.

    The `:-default` form is handled by env-var expansion, which does not know
    CLAUDE_PLUGIN_ROOT, so the default always won and the server launched against
    the user's own project directory instead. Only the bare form is substituted by
    the plugin loader.
    """
    for arg in server_config()["args"]:
        assert ":-" not in arg, (
            f"{arg!r} uses a :-default; CLAUDE_PLUGIN_ROOT must be bare or it "
            "expands to the default and the server launches from the wrong directory"
        )


def test_launcher_path_exists_and_is_executable():
    args = server_config()["args"]
    assert len(args) == 1, f"expected a single script argument, got {args}"
    script = REPO / args[0].replace("${CLAUDE_PLUGIN_ROOT}/", "")
    assert script.is_file(), f"{script} is referenced by .mcp.json but does not exist"
    assert script.stat().st_mode & 0o111, f"{script} is not executable"


def test_config_does_not_source_dotenv():
    """The old config did `source .env`, which silently depended on the client's cwd.

    Credentials now resolve from ~/.tastytrade-mcp/credentials.json or the
    environment, both independent of where the server is launched from.
    """
    raw = MCP_CONFIG.read_text()
    assert "source .env" not in raw
    assert "TT_SECRET" not in raw, "a credential must never be named in the plugin config"
    assert "TT_REFRESH" not in raw


def test_manifest_version_is_semver():
    """Version is the plugin cache key, so a malformed one lands users in a stray directory."""
    version = json.loads(PLUGIN_MANIFEST.read_text())["version"]
    parts = version.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts), f"version {version!r} must be MAJOR.MINOR.PATCH"
