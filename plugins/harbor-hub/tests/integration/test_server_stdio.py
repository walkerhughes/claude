"""Drive the real server over MCP stdio against the live Harbor hub.

Needs HARBOR_API_KEY (mint via `harbor auth login`). Run with `make test-integration`.
"""

import json
import os
import sys
from contextlib import asynccontextmanager

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("HARBOR_API_KEY"), reason="needs HARBOR_API_KEY"
    ),
]

READ_TOOLS = {
    "whoami",
    "list_jobs",
    "get_job_overview",
    "get_job_trials",
    "get_trial_detail",
    "check_job_upload",
    "check_task_published",
    "resolve_dataset",
}
WRITE_TOOLS = {
    "upload_job",
    "publish_task",
    "publish_dataset",
    "download_job",
    "set_job_visibility",
    "share_job",
    "delete_job",
}


# Not a pytest fixture: stdio_client uses anyio cancel scopes, which must be
# entered and exited in the same task. pytest-asyncio runs async-gen fixture
# setup and teardown in different tasks, so each test opens its own session.
@asynccontextmanager
async def open_session():
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "harbor_mcp.server"],
        env=dict(os.environ),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            yield s


async def call(session: ClientSession, tool: str, **args) -> dict:
    result = await session.call_tool(tool, args)
    assert result.content and result.content[0].type == "text"
    return json.loads(result.content[0].text)


async def test_lists_all_tools_with_schemas():
    async with open_session() as session:
        tools = (await session.list_tools()).tools
        assert {t.name for t in tools} == READ_TOOLS | WRITE_TOOLS
        for t in tools:
            assert t.description, f"{t.name} has no description"
            assert t.inputSchema.get("type") == "object", (
                f"{t.name} has no input schema"
            )


async def test_whoami_returns_user_id():
    async with open_session() as session:
        payload = await call(session, "whoami")
        assert payload.get("authenticated") is True
        assert payload.get("user_id")
        key = os.environ["HARBOR_API_KEY"]
        assert key not in json.dumps(payload)


async def test_list_jobs_shape():
    async with open_session() as session:
        payload = await call(session, "list_jobs", page_size=5)
        assert "jobs" in payload and isinstance(payload["jobs"], list)
        assert {"page", "page_size", "total", "total_pages"} <= payload.keys()


async def test_check_task_published_missing_is_not_an_error():
    async with open_session() as session:
        payload = await call(
            session,
            "check_task_published",
            org="harbor-mcp-integration",
            name="no-such-task",
        )
        assert payload.get("published") is False
        assert "error" not in payload


async def test_write_tool_refuses_without_flag():
    async with open_session() as session:
        # The spawned server inherited this test process's env; only meaningful
        # when writes are not enabled there.
        if os.environ.get("HARBOR_MCP_ENABLE_WRITES", "").lower() in (
            "1",
            "true",
            "yes",
        ):
            pytest.skip("HARBOR_MCP_ENABLE_WRITES is set in this environment")
        payload = await call(session, "delete_job", job_id="0" * 32, confirm=True)
        assert "disabled" in payload["error"].lower()
        assert payload["suggestions"]
