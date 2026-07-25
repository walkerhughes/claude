"""Tests for credential resolution.

This is a trust boundary: the file under test grants full brokerage access,
including order placement when trading is enabled.
"""

import json
import os

import pytest

from src.credentials import (
    DEFAULT_BASE_URL,
    ENV_VARS,
    CredentialsError,
    resolve_credentials,
)

pytestmark = pytest.mark.unit

COMPLETE = {"client_id": "cid", "client_secret": "sec", "refresh_token": "ref"}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("API_BASE_URL", raising=False)


def write_creds(tmp_path, data, mode=0o600):
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps(data))
    path.chmod(mode)
    return path


def test_env_takes_precedence_over_file(tmp_path, monkeypatch):
    path = write_creds(tmp_path, {**COMPLETE, "client_id": "from-file"})
    for field, var in ENV_VARS.items():
        monkeypatch.setenv(var, f"env-{field}")

    creds = resolve_credentials(path)

    assert creds.client_id == "env-client_id"
    assert creds.source == "env"


def test_reads_file_when_env_is_empty(tmp_path):
    path = write_creds(tmp_path, COMPLETE)

    creds = resolve_credentials(path)

    assert (creds.client_id, creds.client_secret, creds.refresh_token) == ("cid", "sec", "ref")
    assert creds.source == str(path)
    assert creds.base_url == DEFAULT_BASE_URL


def test_partial_env_is_an_error_not_a_silent_fallthrough(tmp_path, monkeypatch):
    """A half-set environment must fail loudly.

    Falling through to the file would pair a file secret with an env id and
    surface as a 401 that looks like a revoked token.
    """
    write_creds(tmp_path, COMPLETE)
    monkeypatch.setenv("TT_CLIENT_ID", "cid")

    with pytest.raises(CredentialsError) as exc:
        resolve_credentials(tmp_path / "credentials.json")

    assert "TT_SECRET" in str(exc.value)
    assert "TT_REFRESH" in str(exc.value)


def test_refuses_a_group_or_world_readable_file(tmp_path):
    path = write_creds(tmp_path, COMPLETE, mode=0o644)

    with pytest.raises(CredentialsError) as exc:
        resolve_credentials(path)

    assert "chmod 600" in str(exc.value)


def test_missing_file_names_both_options(tmp_path):
    with pytest.raises(CredentialsError) as exc:
        resolve_credentials(tmp_path / "credentials.json")

    message = str(exc.value)
    assert "TT_CLIENT_ID" in message
    assert "credentials.json" in message


def test_file_missing_a_key_says_which(tmp_path):
    path = write_creds(tmp_path, {"client_id": "cid", "client_secret": "sec"})

    with pytest.raises(CredentialsError) as exc:
        resolve_credentials(path)

    assert "refresh_token" in str(exc.value)


def test_malformed_json_is_reported_as_such(tmp_path):
    path = tmp_path / "credentials.json"
    path.write_text("{not json")
    path.chmod(0o600)

    with pytest.raises(CredentialsError) as exc:
        resolve_credentials(path)

    assert "not valid JSON" in str(exc.value)


def test_base_url_precedence(tmp_path, monkeypatch):
    """File value wins over API_BASE_URL, which wins over the default."""
    path = write_creds(tmp_path, {**COMPLETE, "base_url": "file.example.com"})
    monkeypatch.setenv("API_BASE_URL", "env.example.com")
    assert resolve_credentials(path).base_url == "file.example.com"

    path = write_creds(tmp_path, COMPLETE)
    assert resolve_credentials(path).base_url == "env.example.com"

    monkeypatch.delenv("API_BASE_URL")
    assert resolve_credentials(path).base_url == DEFAULT_BASE_URL


def test_never_echoes_the_secret_in_errors(tmp_path):
    """A raised error must not leak the secret it just read."""
    path = write_creds(tmp_path, {"client_id": "cid", "client_secret": "SUPERSECRET"})

    with pytest.raises(CredentialsError) as exc:
        resolve_credentials(path)

    assert "SUPERSECRET" not in str(exc.value)


def test_source_is_reported_without_the_secret(tmp_path):
    path = write_creds(tmp_path, COMPLETE)
    creds = resolve_credentials(path)
    assert creds.source == str(path)
    assert "sec" not in creds.source
    assert os.environ.get("TT_SECRET") is None


@pytest.mark.asyncio
async def test_credentials_error_becomes_a_guided_tool_error():
    """CredentialsError must not escape guarded_tool as a raw exception."""
    from src.infra.errors import guarded_tool

    @guarded_tool
    async def tool() -> str:
        raise CredentialsError("no credentials found at /x/credentials.json")

    payload = json.loads(await tool())
    assert "credentials.json" in payload["error"]
    assert payload["suggestions"]


@pytest.mark.asyncio
async def test_unexpected_exception_never_leaks_a_traceback():
    """The guarded_tool docstring promises this; before the catch-all it was false."""
    from src.infra.errors import guarded_tool

    @guarded_tool
    async def tool() -> str:
        raise ZeroDivisionError("boom")

    payload = json.loads(await tool())
    assert payload["error"] == "ZeroDivisionError: boom"
    assert "Traceback" not in json.dumps(payload)
