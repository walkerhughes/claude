import json
from pathlib import Path

import pytest

from harbor_mcp.tools.base import fmt, truncate, writes_enabled


def test_fmt_is_compact_and_stringifies():
    assert fmt({"p": Path("/tmp/x"), "n": 1}) == '{"p":"/tmp/x","n":1}'


def test_truncate_below_limit_passthrough():
    items, note = truncate([1, 2], 5)
    assert items == [1, 2] and note is None


def test_truncate_caps_and_notes():
    items, note = truncate(list(range(10)), 3)
    assert items == [0, 1, 2]
    assert "3 of 10" in note


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("true", True),
        ("1", True),
        ("YES", True),
        ("false", False),
        ("", False),
        ("no", False),
    ],
)
def test_writes_enabled(monkeypatch, value, expected):
    monkeypatch.setenv("HARBOR_MCP_ENABLE_WRITES", value)
    assert writes_enabled() is expected


def test_writes_disabled_when_unset(monkeypatch):
    monkeypatch.delenv("HARBOR_MCP_ENABLE_WRITES", raising=False)
    assert writes_enabled() is False


def test_fmt_roundtrips():
    assert json.loads(fmt({"a": [1, 2]})) == {"a": [1, 2]}
