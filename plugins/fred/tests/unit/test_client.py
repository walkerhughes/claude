"""Key resolution, parameter cleaning, and retry."""

import json

import httpx
import pytest

from src.client import CredentialsError, FredClient, _clean_params, resolve_api_key

from ..conftest import DUMMY_KEY

pytestmark = pytest.mark.unit


class TestResolveApiKey:
    def test_environment_wins(self):
        assert resolve_api_key() == DUMMY_KEY

    def test_falls_back_to_the_credentials_file(self, monkeypatch, tmp_path):
        monkeypatch.delenv("FRED_API_KEY")
        path = tmp_path / "credentials.json"
        path.write_text(json.dumps({"api_key": "0123456789abcdef0123456789abcdef"}))
        monkeypatch.setattr("src.client.CREDENTIALS_PATH", path)
        assert resolve_api_key() == "0123456789abcdef0123456789abcdef"

    def test_blank_environment_falls_through_to_the_file(self, monkeypatch, tmp_path):
        # An exported-but-empty FRED_API_KEY is what .mcp.json's "${FRED_API_KEY:-}"
        # produces when the user has not set one, so it must not shadow the file.
        monkeypatch.setenv("FRED_API_KEY", "   ")
        path = tmp_path / "credentials.json"
        path.write_text(json.dumps({"api_key": "0123456789abcdef0123456789abcdef"}))
        monkeypatch.setattr("src.client.CREDENTIALS_PATH", path)
        assert resolve_api_key() == "0123456789abcdef0123456789abcdef"

    def test_neither_set_names_both_locations(self, monkeypatch):
        monkeypatch.delenv("FRED_API_KEY")
        with pytest.raises(CredentialsError) as exc:
            resolve_api_key()
        message = str(exc.value)
        assert "FRED_API_KEY" in message
        assert "credentials.json" in message
        assert "fredaccount.stlouisfed.org" in message

    def test_malformed_key_is_caught_locally(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "NOT-A-REAL-KEY")
        with pytest.raises(CredentialsError, match="32 lowercase alphanumeric"):
            resolve_api_key()

    def test_the_key_is_never_echoed(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "SECRETSECRETSECRETSECRETSECRET12")
        with pytest.raises(CredentialsError) as exc:
            resolve_api_key()
        assert "SECRET" not in str(exc.value)

    def test_unparseable_credentials_file(self, monkeypatch, tmp_path):
        monkeypatch.delenv("FRED_API_KEY")
        path = tmp_path / "credentials.json"
        path.write_text("{not json")
        monkeypatch.setattr("src.client.CREDENTIALS_PATH", path)
        with pytest.raises(CredentialsError, match="could not be read as JSON"):
            resolve_api_key()

    def test_credentials_file_without_the_field(self, monkeypatch, tmp_path):
        monkeypatch.delenv("FRED_API_KEY")
        path = tmp_path / "credentials.json"
        path.write_text(json.dumps({"key": "wrong field name"}))
        monkeypatch.setattr("src.client.CREDENTIALS_PATH", path)
        with pytest.raises(CredentialsError, match='no "api_key" field'):
            resolve_api_key()


class TestCleanParams:
    def test_drops_unset_values(self):
        assert _clean_params({"a": 1, "b": None, "c": "", "d": []}) == {"a": "1"}

    def test_renders_booleans_and_lists_the_way_fred_wants(self):
        cleaned = _clean_params({"flag": True, "off": False, "ids": ["A", "B"]})
        assert cleaned == {"flag": "true", "off": "false", "ids": "A,B"}

    def test_zero_survives(self):
        # 0 is a real value for offset and for category_id (the FRED root category).
        assert _clean_params({"offset": 0, "category_id": 0}) == {"offset": "0", "category_id": "0"}


class TestGet:
    async def test_injects_the_key_and_file_type(self):
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(request.url.params)
            return httpx.Response(200, json={"ok": True})

        client = FredClient(transport=httpx.MockTransport(handler))
        assert await client.get("/series", series_id="UNRATE") == {"ok": True}
        assert seen == {"series_id": "UNRATE", "api_key": DUMMY_KEY, "file_type": "json"}
        await client.close()

    async def test_retries_429_then_succeeds(self, monkeypatch):
        monkeypatch.setattr("src.client._BACKOFFS", (0, 0, 0))
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(429, json={"error_code": 429})
            return httpx.Response(200, json={"ok": True})

        client = FredClient(transport=httpx.MockTransport(handler))
        assert await client.get("/series") == {"ok": True}
        assert calls["n"] == 2
        await client.close()

    async def test_gives_up_after_the_backoffs_run_out(self, monkeypatch):
        monkeypatch.setattr("src.client._BACKOFFS", (0, 0, 0))
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(429, json={"error_code": 429})

        client = FredClient(transport=httpx.MockTransport(handler))
        with pytest.raises(httpx.HTTPStatusError):
            await client.get("/series")
        assert calls["n"] == 4  # the first attempt plus one per backoff
        await client.close()

    async def test_400_is_not_retried(self, monkeypatch):
        monkeypatch.setattr("src.client._BACKOFFS", (0, 0, 0))
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(400, json={"error_code": 400, "error_message": "Bad Request."})

        client = FredClient(transport=httpx.MockTransport(handler))
        with pytest.raises(httpx.HTTPStatusError):
            await client.get("/series")
        assert calls["n"] == 1
        await client.close()

    async def test_a_missing_key_surfaces_at_call_time_not_construction(self, monkeypatch):
        monkeypatch.delenv("FRED_API_KEY")
        client = FredClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
        with pytest.raises(CredentialsError):
            await client.get("/series")


class TestBaseUrl:
    def test_defaults_to_the_real_api(self):
        assert FredClient().base_url == "https://api.stlouisfed.org/fred"

    def test_the_environment_can_point_it_at_a_mock(self, monkeypatch):
        # This is what lets the eval benchmark run against a local mock with no key
        # and no possibility of reaching the real API. .env.example documented it
        # before the code read it.
        monkeypatch.setenv("FRED_BASE_URL", "http://localhost:8080/fred")
        assert FredClient().base_url == "http://localhost:8080/fred"

    def test_an_explicit_argument_beats_the_environment(self, monkeypatch):
        monkeypatch.setenv("FRED_BASE_URL", "http://localhost:8080/fred")
        assert FredClient(base_url="http://other:9/fred").base_url == "http://other:9/fred"

    def test_a_trailing_slash_does_not_double_up(self, monkeypatch):
        monkeypatch.setenv("FRED_BASE_URL", "http://localhost:8080/fred/ ")
        assert FredClient().base_url == "http://localhost:8080/fred"
