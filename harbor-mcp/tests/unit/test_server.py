"""Tests for the .env loader that backs the plugin's credential precedence."""

import os

import pytest

from harbor_mcp.server import load_dotenv


@pytest.fixture(autouse=True)
def isolated_environ(monkeypatch):
    """Give each test a throwaway os.environ.

    load_dotenv assigns into os.environ directly, which monkeypatch.delenv would
    not undo. Swapping the whole mapping keeps a test's keys from leaking.
    """
    monkeypatch.setattr(os, "environ", dict(os.environ))


def test_loads_keys_from_env_file(tmp_path):
    (tmp_path / ".env").write_text("HARBOR_API_KEY=sk-harbor-abc_secret\n")
    os.environ.pop("HARBOR_API_KEY", None)

    assert load_dotenv(tmp_path) == tmp_path / ".env"
    assert os.environ["HARBOR_API_KEY"] == "sk-harbor-abc_secret"


def test_real_env_wins_over_file(tmp_path):
    """Precedence 1 beats precedence 2: the client's config outranks the file."""
    (tmp_path / ".env").write_text("HARBOR_API_KEY=from-file\n")
    os.environ["HARBOR_API_KEY"] = "from-environment"

    load_dotenv(tmp_path)

    assert os.environ["HARBOR_API_KEY"] == "from-environment"


def test_finds_env_in_parent_directory(tmp_path):
    (tmp_path / ".env").write_text("HARBOR_MCP_ENABLE_WRITES=true\n")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    os.environ.pop("HARBOR_MCP_ENABLE_WRITES", None)

    assert load_dotenv(nested) == tmp_path / ".env"
    assert os.environ["HARBOR_MCP_ENABLE_WRITES"] == "true"


def test_missing_env_file_is_not_an_error(tmp_path):
    """The `harbor auth login` path relies on this: no .env is normal."""
    assert load_dotenv(tmp_path) is None


def test_parses_comments_quotes_blanks_and_export(tmp_path):
    (tmp_path / ".env").write_text(
        "\n"
        "# a comment\n"
        'QUOTED="quoted value"\n'
        "SINGLE='single'\n"
        "export EXPORTED=exported\n"
        "  SPACED  =  spaced  \n"
        "NOT_AN_ASSIGNMENT\n"
    )

    load_dotenv(tmp_path)

    assert os.environ["QUOTED"] == "quoted value"
    assert os.environ["SINGLE"] == "single"
    assert os.environ["EXPORTED"] == "exported"
    assert os.environ["SPACED"] == "spaced"
    assert "NOT_AN_ASSIGNMENT" not in os.environ


def test_unreadable_env_file_does_not_raise(tmp_path):
    """A corrupt .env degrades to the credentials.json path instead of crashing."""
    (tmp_path / ".env").write_bytes(b"\xff\xfe not utf-8 \x00")

    assert load_dotenv(tmp_path) is None
