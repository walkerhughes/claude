import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from harbor.db.client import ResolvedTaskVersion

from harbor_mcp.tools import register_all, registry


def make_task_row(org: str, name: str, content_hash: str) -> dict:
    return {
        "task_version": {
            "content_hash": content_hash,
            "package": {"name": name, "org": {"name": org}},
        }
    }


@pytest.fixture
def fake_registry_db(monkeypatch) -> SimpleNamespace:
    db = SimpleNamespace(
        resolve_task_version=AsyncMock(),
        resolve_dataset_version=AsyncMock(),
        get_dataset_version_tasks=AsyncMock(),
    )
    monkeypatch.setattr(registry, "_registry", lambda: db)
    return db


async def test_check_task_published_happy(fake_registry_db):
    fake_registry_db.resolve_task_version.return_value = ResolvedTaskVersion(
        id="tv-1", archive_path="tasks/hello.tar.zst", content_hash="abc123"
    )

    payload = json.loads(await registry.check_task_published("acme", "hello-world"))
    fake_registry_db.resolve_task_version.assert_awaited_once_with(
        "acme", "hello-world", "latest"
    )
    assert payload == {
        "published": True,
        "org": "acme",
        "name": "hello-world",
        "ref": "latest",
        "task_version_id": "tv-1",
        "content_hash": "abc123",
        "archive_path": "tasks/hello.tar.zst",
    }


async def test_check_task_published_not_published(fake_registry_db):
    fake_registry_db.resolve_task_version.side_effect = ValueError(
        "Task version not found: acme/missing@latest"
    )

    payload = json.loads(await registry.check_task_published("acme", "missing"))
    assert payload["published"] is False
    assert payload["org"] == "acme"
    assert payload["name"] == "missing"
    assert "Task version not found" in payload["detail"]
    assert "error" not in payload


async def test_resolve_dataset_happy(fake_registry_db):
    fake_registry_db.resolve_dataset_version.return_value = (
        {"name": "terminal-bench", "visibility": "public", "description": "TB tasks"},
        {"id": "dv-1", "revision": 3, "content_hash": "deadbeef"},
    )
    fake_registry_db.get_dataset_version_tasks.return_value = [
        make_task_row("acme", "task-a", "hash-a"),
        make_task_row("acme", "task-b", "hash-b"),
        {"task_version": None},
    ]

    payload = json.loads(await registry.resolve_dataset("acme", "terminal-bench"))
    fake_registry_db.resolve_dataset_version.assert_awaited_once_with(
        "acme", "terminal-bench", "latest"
    )
    fake_registry_db.get_dataset_version_tasks.assert_awaited_once_with("dv-1")
    assert payload["org"] == "acme"
    assert payload["name"] == "terminal-bench"
    assert payload["revision"] == 3
    assert payload["visibility"] == "public"
    assert payload["dataset_version_id"] == "dv-1"
    assert payload["content_hash"] == "deadbeef"
    assert payload["n_tasks"] == 2
    assert payload["tasks"] == [
        {"task": "acme/task-a", "content_hash": "hash-a"},
        {"task": "acme/task-b", "content_hash": "hash-b"},
    ]
    assert "note" not in payload


async def test_resolve_dataset_truncates_tasks(fake_registry_db):
    fake_registry_db.resolve_dataset_version.return_value = (
        {"name": "big-set"},
        {"id": "dv-2", "revision": 1},
    )
    fake_registry_db.get_dataset_version_tasks.return_value = [
        make_task_row("acme", f"task-{i}", f"hash-{i}") for i in range(60)
    ]

    payload = json.loads(await registry.resolve_dataset("acme", "big-set"))
    assert payload["n_tasks"] == 60
    assert len(payload["tasks"]) == registry.DATASET_TASKS_CAP
    assert "50 of 60" in payload["note"]


async def test_resolve_dataset_not_found(fake_registry_db):
    fake_registry_db.resolve_dataset_version.side_effect = ValueError(
        "Tag 'latest' not found for dataset 'acme/missing'"
    )

    payload = json.loads(await registry.resolve_dataset("acme", "missing"))
    assert "not found" in payload["error"]
    fake_registry_db.get_dataset_version_tasks.assert_not_awaited()


def test_register_all_registers_every_tool():
    registered: list[str] = []

    class FakeMCP:
        def tool(self):
            def decorator(fn):
                registered.append(fn.__name__)
                return fn

            return decorator

    register_all(FakeMCP())
    assert registered == [
        "whoami",
        "list_jobs",
        "get_job_overview",
        "get_job_trials",
        "get_trial_detail",
        "check_job_upload",
        "check_task_published",
        "resolve_dataset",
        "upload_job",
        "publish_task",
        "publish_dataset",
        "download_job",
        "set_job_visibility",
        "share_job",
        "delete_job",
    ]
