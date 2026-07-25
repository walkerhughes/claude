"""Guards on the shipped plugin config.

These exist because a bad .mcp.json fails at MCP connect time with an opaque
-32000 that no other test can see, and the first three attempts at this file all
shipped broken.
"""

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MCP_CONFIG = REPO / ".mcp.json"
PLUGIN_MANIFEST = REPO / ".claude-plugin" / "plugin.json"


def server_config() -> dict:
    return json.loads(MCP_CONFIG.read_text())["mcpServers"]["harbor-hub"]


def test_plugin_root_has_no_default_fallback():
    """`${CLAUDE_PLUGIN_ROOT:-.}` silently expands to `.`, not the plugin root.

    The `:-default` form is handled by env-var expansion, which does not know
    CLAUDE_PLUGIN_ROOT, so the default always won and the server was launched
    against the user's own project directory. Only the bare form is substituted
    by the plugin loader.
    """
    for arg in server_config()["args"]:
        assert ":-" not in arg, (
            f"{arg!r} uses a :-default; CLAUDE_PLUGIN_ROOT must be bare or it "
            "expands to the default and the server launches from the wrong "
            "directory"
        )


def test_launcher_path_exists():
    """The referenced script must actually ship, or bash exits before the server runs."""
    args = server_config()["args"]
    assert len(args) == 1, f"expected a single script argument, got {args}"
    relative = args[0].replace("${CLAUDE_PLUGIN_ROOT}/", "")
    script = REPO / relative
    assert script.is_file(), f"{script} is referenced by .mcp.json but does not exist"
    assert script.stat().st_mode & 0o111, f"{script} is not executable"


def test_manifest_version_matches_nothing_stale():
    """Version is the plugin cache key, so it must be a real semver triple.

    A malformed version would land users in an unexpected cache directory.
    """
    version = json.loads(PLUGIN_MANIFEST.read_text())["version"]
    parts = version.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts), (
        f"version {version!r} must be MAJOR.MINOR.PATCH"
    )
