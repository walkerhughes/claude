"""The declared dependency ranges must exclude versions that break the server.

uv.lock pins what *we* run, so nothing else in this suite notices when a
declared range admits a broken release: `pip install harbor-mcp` in the eval
images (and for anyone installing the plugin) resolves fresh and ignores the
lock entirely.

That gap shipped once. `mcp>=1.2` was unbounded, mcp 2.0.0 dropped
`mcp.server.fastmcp`, and every fresh install crashed on import with
ModuleNotFoundError while the locked local checkout stayed green. It surfaced
only when the eval gate found an agent talking to a dead MCP server.
"""

import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _requirement(name: str) -> Requirement:
    deps = tomllib.loads(PYPROJECT.read_text())["project"]["dependencies"]
    for raw in deps:
        req = Requirement(raw)
        if req.name == name:
            return req
    pytest.fail(f"{name} is not a declared dependency of harbor-mcp")


def test_mcp_excludes_2_0_which_removed_fastmcp() -> None:
    """server.py imports mcp.server.fastmcp, gone in mcp 2.x.

    Lifting this cap means porting server.py off mcp.server.fastmcp first;
    change the test in the same commit that does the port.
    """
    assert not _requirement("mcp").specifier.contains("2.0.0"), (
        "the declared mcp range admits 2.0.0, which has no mcp.server.fastmcp; "
        "a fresh `pip install harbor-mcp` would crash on import"
    )


def test_harbor_is_pinned_exactly() -> None:
    """We import harbor internals, so a floating range is a live grenade."""
    specifier = _requirement("harbor").specifier
    assert [s.operator for s in specifier] == ["=="], (
        f"harbor must be pinned exactly, got {specifier}"
    )
