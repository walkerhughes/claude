"""Full product loop against the live hub: run a real harbor job on
HARBOR_TEST_ENV (docker by default, modal to toggle), then upload, verify,
download, and delete it entirely through the MCP server over stdio.

Needs HARBOR_API_KEY. Run with `make test-e2e`; set HARBOR_TEST_ENV=modal to
exercise the cloud path (Modal credentials required; the fixture task is
single-container, which modal supports).
"""

import json
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not os.environ.get("HARBOR_API_KEY"), reason="needs HARBOR_API_KEY"
    ),
]

# Shared fixture (also backs the eval runners' job bootstrap); see its README.
FIXTURE_TASK = Path(__file__).parent / "fixtures" / "hello-world"
JOB_NAME = "harbor-mcp-e2e"
RUN_TIMEOUT_SEC = 1200  # first run docker-builds the fixture image


@pytest.fixture(scope="session")
def job_dir(tmp_path_factory) -> Path:
    """Run the fixture task once with the oracle agent (no LLM cost), WITHOUT
    --upload; uploading is the MCP server's job in the test body."""
    test_env = os.environ.get("HARBOR_TEST_ENV", "docker")
    jobs_dir = tmp_path_factory.mktemp("jobs")
    harbor_bin = Path(sys.executable).parent / "harbor"
    subprocess.run(
        [
            str(harbor_bin),
            "run",
            "-p",
            str(FIXTURE_TASK),
            "-a",
            "oracle",
            "-e",
            test_env,
            "-o",
            str(jobs_dir),
            "--job-name",
            JOB_NAME,
            "-q",
        ],
        check=True,
        timeout=RUN_TIMEOUT_SEC,
    )
    d = jobs_dir / JOB_NAME
    result = d / "result.json"
    if not result.exists():
        pytest.fail(f"harbor run produced no result.json under {d}")
    # Fail legibly if the environment could not run the trial (e.g. a modal
    # image-build RemoteError) instead of letting a rewardless trial surface
    # downstream. The job result carries success in stats, not trial_results.
    stats = json.loads(result.read_text()).get("stats", {})
    if stats.get("n_errored_trials") or not stats.get("n_completed_trials"):
        pytest.fail(
            f"oracle did not solve the fixture on env={test_env}; "
            f"the harbor run reported no completed trial. stats={stats}"
        )
    return d


# Same rationale as the integration suite: anyio cancel scopes must enter and
# exit in one task, so no async-gen pytest fixture; each test opens a session.
@asynccontextmanager
async def open_session():
    env = dict(os.environ)
    env["HARBOR_MCP_ENABLE_WRITES"] = "true"
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


async def test_upload_verify_download_delete_roundtrip(job_dir, tmp_path):
    job_id = json.loads((job_dir / "result.json").read_text())["id"]

    async with open_session() as session:
        # Upload the locally produced job through the MCP server.
        await call(session, "upload_job", job_dir=str(job_dir))

        # Did the upload work? The question this MCP exists to answer.
        chk = await call(session, "check_job_upload", job_id=job_id)
        assert chk["exists"] is True
        assert chk["archive_present"] is True
        assert chk["n_trials_uploaded"] == 1

        # The oracle solved the fixture task, so the trial carries reward 1.
        trials = await call(session, "get_job_trials", job_id=job_id)
        rows = trials["trials"]
        assert len(rows) == 1
        assert rows[0].get("reward") == 1, rows[0]

        detail = await call(session, "get_trial_detail", trial_id=rows[0]["id"])
        assert detail

        # Round-trip the artifacts back to disk.
        dl = await call(
            session, "download_job", job_id=job_id, dest_dir=str(tmp_path / "dl")
        )
        downloaded = Path(dl["output_dir"])
        assert (downloaded / "result.json").exists()

        # Clean up on the hub and confirm it is gone.
        rm = await call(session, "delete_job", job_id=job_id, confirm=True)
        assert rm["deleted"] is True
        gone = await call(session, "check_job_upload", job_id=job_id)
        assert gone["exists"] is False
