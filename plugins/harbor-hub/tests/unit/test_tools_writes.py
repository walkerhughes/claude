import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from harbor.download.downloader import JobDownloadResult
from harbor.publisher.publisher import DatasetPublishResult, PublishResult
from harbor.upload.uploader import JobUploadResult

from harbor_mcp.tools import writes

JOB_ID = "0b2a2ae6-6c86-4c4f-9d5e-1f2a3b4c5d6e"

TOOL_CALLS = [
    (writes.upload_job, {"job_dir": "/tmp/job"}),
    (writes.publish_task, {"task_dir": "/tmp/task"}),
    (writes.publish_dataset, {"dataset_dir": "/tmp/dataset"}),
    (writes.download_job, {"job_id": JOB_ID, "dest_dir": "/tmp/out"}),
    (writes.set_job_visibility, {"job_id": JOB_ID, "visibility": "public"}),
    (writes.share_job, {"job_id": JOB_ID, "usernames": "alice"}),
    (writes.delete_job, {"job_id": JOB_ID, "confirm": True}),
]


@pytest.fixture
def writes_on(monkeypatch):
    monkeypatch.setenv("HARBOR_MCP_ENABLE_WRITES", "true")


@pytest.fixture
def writes_off(monkeypatch):
    monkeypatch.delenv("HARBOR_MCP_ENABLE_WRITES", raising=False)


@pytest.mark.parametrize(
    ("tool", "kwargs"), TOOL_CALLS, ids=[t.__name__ for t, _ in TOOL_CALLS]
)
async def test_every_tool_blocked_without_env_flag(writes_off, tool, kwargs):
    payload = json.loads(await tool(**kwargs))
    assert payload["error"] == "Write tools are disabled."
    assert any("HARBOR_MCP_ENABLE_WRITES=true" in s for s in payload["suggestions"])


async def test_delete_job_blocked_without_confirm(writes_on):
    payload = json.loads(await writes.delete_job(JOB_ID))
    assert "confirm=true" in payload["error"]
    assert "permanent" in payload["error"]
    assert any(JOB_ID in s for s in payload["suggestions"])


async def test_upload_job_happy_path(writes_on, monkeypatch):
    result = JobUploadResult(
        job_name="my-job",
        job_id=JOB_ID,
        visibility="private",
        n_trials_uploaded=3,
    )
    uploader = MagicMock(upload_job=AsyncMock(return_value=result))
    monkeypatch.setattr(writes, "_uploader", lambda: uploader)

    payload = json.loads(await writes.upload_job("/tmp/job", visibility="private"))
    assert payload["job_name"] == "my-job"
    assert payload["job_id"] == JOB_ID
    assert payload["n_trials_uploaded"] == 3
    assert "trial_results" not in payload
    uploader.upload_job.assert_awaited_once_with(Path("/tmp/job"), visibility="private")


async def test_upload_job_default_visibility_is_none(writes_on, monkeypatch):
    result = JobUploadResult(job_name="j", job_id=JOB_ID, visibility="private")
    uploader = MagicMock(upload_job=AsyncMock(return_value=result))
    monkeypatch.setattr(writes, "_uploader", lambda: uploader)

    await writes.upload_job("/tmp/job")
    assert uploader.upload_job.await_args.kwargs["visibility"] is None


async def test_upload_job_rejects_invalid_visibility(writes_on):
    payload = json.loads(await writes.upload_job("/tmp/job", visibility="internal"))
    assert "Invalid visibility" in payload["error"]
    assert payload["suggestions"]


async def test_publish_task_happy_path(writes_on, monkeypatch):
    result = PublishResult(
        name="hello-world",
        content_hash="abc123",
        archive_path="/tmp/archive.tgz",
        file_count=4,
        archive_size_bytes=1024,
        build_time_sec=0.1,
        upload_time_sec=0.2,
        revision=2,
        tags=["stable"],
    )
    publisher = MagicMock(publish_task=AsyncMock(return_value=result))
    monkeypatch.setattr(writes, "_publisher", lambda: publisher)

    payload = json.loads(
        await writes.publish_task("/tmp/task", visibility="public", tags="stable, v1")
    )
    assert payload["name"] == "hello-world"
    assert payload["revision"] == 2
    assert "archive_path" not in payload
    assert "rpc_time_sec" not in payload
    publisher.publish_task.assert_awaited_once_with(
        Path("/tmp/task"), tags={"stable", "v1"}, visibility="public"
    )


async def test_publish_task_rejects_invalid_visibility(writes_on):
    payload = json.loads(await writes.publish_task("/tmp/task", visibility="hidden"))
    assert "Invalid visibility" in payload["error"]


async def test_publish_dataset_happy_path(writes_on, monkeypatch):
    result = DatasetPublishResult(
        name="my-dataset",
        content_hash="def456",
        revision=1,
        task_count=10,
        file_count=42,
    )
    publisher = MagicMock(publish_dataset=AsyncMock(return_value=result))
    monkeypatch.setattr(writes, "_publisher", lambda: publisher)

    payload = json.loads(await writes.publish_dataset("/tmp/dataset"))
    assert payload["name"] == "my-dataset"
    assert payload["task_count"] == 10
    assert "rpc_time_sec" not in payload
    publisher.publish_dataset.assert_awaited_once_with(
        Path("/tmp/dataset"), tags=None, visibility="private"
    )


async def test_publish_dataset_rejects_invalid_visibility(writes_on):
    payload = json.loads(await writes.publish_dataset("/tmp/d", visibility="secret"))
    assert "Invalid visibility" in payload["error"]


async def test_download_job_happy_path(writes_on, monkeypatch):
    result = JobDownloadResult(
        job_id=JOB_ID,
        job_name="my-job",
        output_dir=Path("/tmp/out/my-job"),
        n_trials_downloaded=5,
    )
    downloader = MagicMock(download_job=AsyncMock(return_value=result))
    monkeypatch.setattr(writes, "_downloader", lambda: downloader)

    payload = json.loads(await writes.download_job(JOB_ID, "/tmp/out", overwrite=True))
    assert payload["job_name"] == "my-job"
    assert payload["output_dir"] == "/tmp/out/my-job"
    assert "manifest_path" not in payload
    downloader.download_job.assert_awaited_once_with(
        uuid.UUID(JOB_ID), Path("/tmp/out"), overwrite=True
    )


async def test_download_job_rejects_invalid_uuid(writes_on):
    payload = json.loads(await writes.download_job("not-a-uuid", "/tmp/out"))
    assert "not a UUID" in payload["error"]
    assert payload["suggestions"]


async def test_set_job_visibility_happy_path(writes_on, monkeypatch):
    db = MagicMock(
        get_job=AsyncMock(return_value={"job_name": "my-job"}),
        update_job_visibility=AsyncMock(),
    )
    monkeypatch.setattr(writes, "_upload_db", lambda: db)

    payload = json.loads(await writes.set_job_visibility(JOB_ID, "public"))
    assert payload == {
        "job_id": JOB_ID,
        "job_name": "my-job",
        "visibility": "public",
        "updated": True,
    }
    db.update_job_visibility.assert_awaited_once_with(uuid.UUID(JOB_ID), "public")


async def test_set_job_visibility_not_found(writes_on, monkeypatch):
    db = MagicMock(
        get_job=AsyncMock(return_value=None), update_job_visibility=AsyncMock()
    )
    monkeypatch.setattr(writes, "_upload_db", lambda: db)

    payload = json.loads(await writes.set_job_visibility(JOB_ID, "private"))
    assert "not found or not accessible" in payload["error"]
    db.update_job_visibility.assert_not_awaited()


async def test_set_job_visibility_rejects_invalid_visibility(writes_on):
    payload = json.loads(await writes.set_job_visibility(JOB_ID, "friends-only"))
    assert "Invalid visibility" in payload["error"]


async def test_set_job_visibility_rejects_invalid_uuid(writes_on):
    payload = json.loads(await writes.set_job_visibility("nope", "public"))
    assert "not a UUID" in payload["error"]


async def test_share_job_happy_path_surfaces_warnings(writes_on, monkeypatch):
    rpc_result = {"shared_orgs": ["acme"], "warnings": ["user bob not found"]}
    db = MagicMock(
        get_job=AsyncMock(return_value={"job_name": "my-job"}),
        add_job_shares=AsyncMock(return_value=rpc_result),
    )
    monkeypatch.setattr(writes, "_upload_db", lambda: db)

    payload = json.loads(
        await writes.share_job(JOB_ID, org_names="acme", usernames="alice, bob")
    )
    assert payload["result"] == rpc_result
    assert payload["org_names"] == ["acme"]
    assert payload["usernames"] == ["alice", "bob"]
    db.add_job_shares.assert_awaited_once_with(
        job_id=uuid.UUID(JOB_ID),
        org_names=["acme"],
        usernames=["alice", "bob"],
        confirm_non_member_orgs=False,
    )


async def test_share_job_not_found(writes_on, monkeypatch):
    db = MagicMock(get_job=AsyncMock(return_value=None), add_job_shares=AsyncMock())
    monkeypatch.setattr(writes, "_upload_db", lambda: db)

    payload = json.loads(await writes.share_job(JOB_ID, usernames="alice"))
    assert "not found or not accessible" in payload["error"]
    db.add_job_shares.assert_not_awaited()


async def test_share_job_requires_a_recipient(writes_on):
    payload = json.loads(await writes.share_job(JOB_ID))
    assert "Nothing to share" in payload["error"]


async def test_share_job_rejects_invalid_uuid(writes_on):
    payload = json.loads(await writes.share_job("bad-id", usernames="alice"))
    assert "not a UUID" in payload["error"]


async def test_delete_job_happy_path(writes_on, monkeypatch):
    hub = MagicMock(delete_job=AsyncMock(return_value=True))
    monkeypatch.setattr(writes, "_hub_client", lambda: hub)

    payload = json.loads(await writes.delete_job(JOB_ID, confirm=True))
    assert payload == {"job_id": JOB_ID, "deleted": True}
    hub.delete_job.assert_awaited_once_with(JOB_ID)


async def test_delete_job_reports_not_deleted(writes_on, monkeypatch):
    hub = MagicMock(delete_job=AsyncMock(return_value=False))
    monkeypatch.setattr(writes, "_hub_client", lambda: hub)

    payload = json.loads(await writes.delete_job(JOB_ID, confirm=True))
    assert "was not deleted" in payload["error"]
    assert payload["suggestions"]


async def test_delete_job_rejects_invalid_uuid(writes_on):
    payload = json.loads(await writes.delete_job("bad-id", confirm=True))
    assert "not a UUID" in payload["error"]
