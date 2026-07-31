"""Read tools over the Harbor package registry: task and dataset versions."""

from functools import cache
from typing import Any

from harbor.db.client import RegistryDB

from harbor_mcp.infra.errors import guarded_tool
from harbor_mcp.tools.base import compact, fmt, truncate

DATASET_TASKS_CAP = 50


@cache
def _registry() -> RegistryDB:
    return RegistryDB()


def _task_entry(row: dict[str, Any]) -> dict[str, Any] | None:
    """Shape one dataset_version_task row into {task, content_hash}."""
    task_version = row.get("task_version")
    if not isinstance(task_version, dict):
        return None
    package = task_version.get("package")
    package = package if isinstance(package, dict) else {}
    org = package.get("org")
    org = org if isinstance(org, dict) else {}
    org_name = org.get("name")
    pkg_name = package.get("name")
    entry = compact(
        {
            "task": f"{org_name}/{pkg_name}" if org_name and pkg_name else None,
            "content_hash": task_version.get("content_hash"),
        }
    )
    return entry or None


@guarded_tool
async def check_task_published(org: str, name: str, ref: str = "latest") -> str:
    """Check whether a task package version exists in the Harbor registry.
    `ref` accepts a tag (e.g. "latest"), a numeric revision, or a sha256
    digest. A missing version returns published=false rather than an error.
    For dataset packages, use resolve_dataset instead."""
    try:
        resolved = await _registry().resolve_task_version(org, name, ref)
    except ValueError as exc:
        return fmt(
            {
                "published": False,
                "org": org,
                "name": name,
                "ref": ref,
                "detail": str(exc),
            }
        )
    return fmt(
        {
            "published": True,
            "org": org,
            "name": name,
            "ref": ref,
            "task_version_id": resolved.id,
            "content_hash": resolved.content_hash,
            "archive_path": resolved.archive_path,
        }
    )


@guarded_tool
async def resolve_dataset(org: str, name: str, ref: str = "latest") -> str:
    """Resolve a dataset package version in the Harbor registry and list its
    member tasks (org/name plus content hash). `ref` accepts a tag (e.g.
    "latest"), a numeric revision, or a sha256 digest. For a single task
    package, use check_task_published instead."""
    db = _registry()
    package, version = await db.resolve_dataset_version(org, name, ref)
    version_id = str(version.get("id") or "")
    task_rows = await db.get_dataset_version_tasks(version_id) if version_id else []
    tasks = [entry for row in task_rows if (entry := _task_entry(row)) is not None]
    shown, note = truncate(tasks, DATASET_TASKS_CAP)
    return fmt(
        compact(
            {
                "org": org,
                "name": package.get("name") or name,
                "ref": ref,
                "revision": version.get("revision"),
                "visibility": package.get("visibility"),
                "description": package.get("description"),
                "dataset_version_id": version_id or None,
                "content_hash": version.get("content_hash"),
                "n_tasks": len(tasks),
                "tasks": shown,
                "note": note,
            }
        )
    )


def register(mcp: Any) -> None:
    for tool in (check_task_published, resolve_dataset):
        mcp.tool()(tool)
