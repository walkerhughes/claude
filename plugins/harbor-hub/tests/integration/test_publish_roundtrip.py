"""Publish -> read-back integration test against a dedicated Harbor test org.

Publishes a scratch task into HARBOR_TEST_ORG (private) via the publish_task
MCP tool, then confirms it with check_task_published. Idempotent: the task
content is static (only the org varies), so a re-run resolves to the same
content hash and publish_task reports skipped=true. The hub has no unpublish
for packages, so the private scratch package persists; that is by design.

Needs HARBOR_API_KEY and HARBOR_TEST_ORG (an org the key's user belongs to;
publishing auto-creates it if missing). Run with `make test-integration`.
"""

import json
import os
import sys
import textwrap
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("HARBOR_API_KEY") and os.environ.get("HARBOR_TEST_ORG")),
        reason="needs HARBOR_API_KEY and HARBOR_TEST_ORG",
    ),
]

SCRATCH_NAME = "harbor-mcp-scratch"


def _write_scratch_task(root: Path, org: str) -> Path:
    """Write a minimal, valid, static task under root, owned by org.

    Only the org varies between runs, so the content hash is stable and a
    re-publish is a no-op on the hub.
    """
    (root / "environment").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "task.toml").write_text(
        textwrap.dedent(f"""\
            version = "1.0"

            [task]
            name = "{org}/{SCRATCH_NAME}"
            authors = []
            keywords = ["harbor-mcp-integration"]

            [verifier]
            timeout_sec = 120.0

            [agent]
            timeout_sec = 120.0

            [environment]
            build_timeout_sec = 600.0
            cpus = 1
            memory_mb = 1024
            storage_mb = 5120
            gpus = 0
            mcp_servers = []
            """)
    )
    (root / "instruction.md").write_text(
        "Scratch task for harbor-mcp integration tests.\n"
    )
    (root / "environment" / "Dockerfile").write_text(
        "FROM python:3.12-slim\n\nWORKDIR /app\n"
    )
    (root / "tests" / "test.sh").write_text(
        "#!/bin/bash\necho 1 > /logs/verifier/reward.txt\n"
    )
    return root


# Same rationale as the other integration suite: anyio cancel scopes must
# enter and exit in one task, so each test opens its own session.
@asynccontextmanager
async def open_session():
    env = dict(os.environ)
    env["HARBOR_MCP_ENABLE_WRITES"] = "true"  # publish_task is a gated write
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "harbor_mcp.server"], env=env
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            yield s


async def call(session: ClientSession, tool: str, **args) -> dict:
    result = await session.call_tool(tool, args)
    assert result.content and result.content[0].type == "text"
    payload = json.loads(result.content[0].text)
    assert "error" not in payload, f"{tool} failed: {payload}"
    return payload


async def test_publish_then_check_roundtrip(tmp_path):
    org = os.environ["HARBOR_TEST_ORG"]
    task_dir = _write_scratch_task(tmp_path / "scratch", org)

    async with open_session() as session:
        published = await call(
            session, "publish_task", task_dir=str(task_dir), visibility="private"
        )
        assert published["name"] == f"{org}/{SCRATCH_NAME}"
        content_hash = published["content_hash"]
        assert content_hash

        # Read the write back through the registry: it is visible and matches.
        checked = await call(
            session, "check_task_published", org=org, name=SCRATCH_NAME
        )
        assert checked["published"] is True
        assert checked["content_hash"] == content_hash
