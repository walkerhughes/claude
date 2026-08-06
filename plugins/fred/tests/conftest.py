"""Shared fixtures.

Every test runs with FRED_API_KEY forced to a valid-shaped dummy, so nothing here can
reach the real API or depend on the developer's own key being set.
"""

import pytest

DUMMY_KEY = "abcdef0123456789abcdef0123456789"


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    monkeypatch.setenv("FRED_API_KEY", DUMMY_KEY)
    # Point the credentials-file fallback at an empty tmp dir so a real
    # ~/.fred-mcp/credentials.json on the machine cannot influence a test.
    monkeypatch.setattr("src.client.CREDENTIALS_PATH", tmp_path / "credentials.json")
    from src import tools

    tools.reset_state()
    yield
    tools.reset_state()
