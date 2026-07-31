"""Write tools for the Harbor hub: upload, publish, download, visibility, delete.

Every tool here mutates hub state (or writes to local disk, for download_job),
so all of them are gated behind HARBOR_MCP_ENABLE_WRITES. delete_job is
additionally gated behind an explicit confirm flag because deletion is
permanent.
"""

import uuid
from functools import cache
from pathlib import Path
from typing import Any, Literal, cast

from harbor_mcp.infra.errors import error_response, guarded_tool
from harbor_mcp.tools.base import fmt, writes_enabled

_VISIBILITIES = ("public", "private")


# Lazy client singletons: constructing these imports heavy harbor internals, so
# defer until a tool runs. cache gives one instance per process; tests
# monkeypatch these accessors.
@cache
def _uploader() -> Any:
    from harbor.upload.uploader import Uploader

    return Uploader()


@cache
def _publisher() -> Any:
    from harbor.publisher.publisher import Publisher

    return Publisher()


@cache
def _downloader() -> Any:
    from harbor.download.downloader import Downloader

    return Downloader()


@cache
def _upload_db() -> Any:
    from harbor.upload.db_client import UploadDB

    return UploadDB()


@cache
def _hub_client() -> Any:
    from harbor.hub.client import HubClient

    return HubClient()


def _writes_disabled() -> str | None:
    """Return the refusal payload when writes are gated off, else None."""
    if writes_enabled():
        return None
    return error_response(
        "Write tools are disabled.",
        suggestions=[
            "Ask the user to export HARBOR_MCP_ENABLE_WRITES=true and restart "
            "the server. Read-only is the intended default."
        ],
    )


def _invalid_visibility(visibility: str) -> str:
    return error_response(
        f"Invalid visibility {visibility!r}.",
        suggestions=['Pass "public" or "private".'],
    )


def _parse_job_id(job_id: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(job_id)
    except ValueError:
        return None


def _invalid_job_id(job_id: str) -> str:
    return error_response(
        f"Invalid job_id {job_id!r}: not a UUID.",
        suggestions=[
            "Pass the job's UUID, e.g. from list_jobs or the id printed by harbor run."
        ],
    )


def _job_not_found(job_id: str) -> str:
    return error_response(
        f"Job {job_id} not found or not accessible.",
        suggestions=[
            "Verify the job_id exists and belongs to your account.",
            "Rows hidden by permissions look identical to missing rows.",
        ],
    )


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


@guarded_tool
async def upload_job(job_dir: str, visibility: str | None = None) -> str:
    """Upload a local harbor job directory to the hub.

    Idempotent and resumable: re-running skips trials already uploaded.
    visibility: "public", "private", or omit (None) to leave an existing
    job's visibility untouched; brand-new jobs default to private.
    """
    if disabled := _writes_disabled():
        return disabled
    if visibility is not None and visibility not in _VISIBILITIES:
        return _invalid_visibility(visibility)
    result = await _uploader().upload_job(
        Path(job_dir),
        visibility=cast(Literal["public", "private"] | None, visibility),
    )
    return fmt(result.model_dump(exclude={"trial_results"}))


@guarded_tool
async def publish_task(
    task_dir: str, visibility: str = "private", tags: str | None = None
) -> str:
    """Publish a local task directory (task.toml + environment) to the hub registry.

    visibility: "public" or "private" (default private).
    tags: optional comma-separated tags, e.g. "stable,v1".
    """
    if disabled := _writes_disabled():
        return disabled
    if visibility not in _VISIBILITIES:
        return _invalid_visibility(visibility)
    tag_set = set(_split_csv(tags)) or None
    result = await _publisher().publish_task(
        Path(task_dir), tags=tag_set, visibility=visibility
    )
    return fmt(result.model_dump(exclude={"archive_path", "rpc_time_sec"}))


@guarded_tool
async def publish_dataset(
    dataset_dir: str, visibility: str = "private", tags: str | None = None
) -> str:
    """Publish a local dataset directory (dataset.toml) to the hub registry.

    visibility: "public" or "private" (default private).
    tags: optional comma-separated tags, e.g. "stable,v1".
    """
    if disabled := _writes_disabled():
        return disabled
    if visibility not in _VISIBILITIES:
        return _invalid_visibility(visibility)
    tag_set = set(_split_csv(tags)) or None
    result = await _publisher().publish_dataset(
        Path(dataset_dir), tags=tag_set, visibility=visibility
    )
    return fmt(result.model_dump(exclude={"rpc_time_sec"}))


@guarded_tool
async def download_job(job_id: str, dest_dir: str, overwrite: bool = False) -> str:
    """Download a hub job's archive and extract it under dest_dir/<job_name>.

    Fails if the target directory already exists unless overwrite=true.
    """
    if disabled := _writes_disabled():
        return disabled
    parsed = _parse_job_id(job_id)
    if parsed is None:
        return _invalid_job_id(job_id)
    result = await _downloader().download_job(
        parsed, Path(dest_dir), overwrite=overwrite
    )
    return fmt(result.model_dump(exclude={"manifest_path"}))


@guarded_tool
async def set_job_visibility(job_id: str, visibility: str) -> str:
    """Flip an existing hub job's visibility to "public" or "private"."""
    if disabled := _writes_disabled():
        return disabled
    if visibility not in _VISIBILITIES:
        return _invalid_visibility(visibility)
    parsed = _parse_job_id(job_id)
    if parsed is None:
        return _invalid_job_id(job_id)
    db = _upload_db()
    job = await db.get_job(parsed)
    if job is None:
        return _job_not_found(job_id)
    await db.update_job_visibility(
        parsed, cast(Literal["public", "private"], visibility)
    )
    return fmt(
        {
            "job_id": str(parsed),
            "job_name": job.get("job_name"),
            "visibility": visibility,
            "updated": True,
        }
    )


@guarded_tool
async def share_job(
    job_id: str, org_names: str | None = None, usernames: str | None = None
) -> str:
    """Share a hub job with organizations and/or users (comma-separated names).

    Sharing grants read access without making the job public. The response
    may include warnings (e.g. unknown users or orgs you are not a member of).
    """
    if disabled := _writes_disabled():
        return disabled
    parsed = _parse_job_id(job_id)
    if parsed is None:
        return _invalid_job_id(job_id)
    orgs = _split_csv(org_names)
    users = _split_csv(usernames)
    if not orgs and not users:
        return error_response(
            "Nothing to share: pass org_names and/or usernames.",
            suggestions=[
                'Pass comma-separated names, e.g. org_names="my-org" or usernames="alice,bob".'
            ],
        )
    db = _upload_db()
    job = await db.get_job(parsed)
    if job is None:
        return _job_not_found(job_id)
    result = await db.add_job_shares(
        job_id=parsed,
        org_names=orgs,
        usernames=users,
        confirm_non_member_orgs=False,
    )
    return fmt(
        {
            "job_id": str(parsed),
            "job_name": job.get("job_name"),
            "org_names": orgs,
            "usernames": users,
            "result": result,
        }
    )


@guarded_tool
async def delete_job(job_id: str, confirm: bool = False) -> str:
    """Delete a hub job's database rows (trials and shares cascade). PERMANENT.

    Deletion cannot be undone. Requires confirm=true; only pass it after the
    user has explicitly approved deleting this specific job. Uploaded archives
    in the storage bucket are not removed, only the database rows go.
    """
    if disabled := _writes_disabled():
        return disabled
    if not confirm:
        return error_response(
            "delete_job requires confirm=true. Deletion is permanent and cannot "
            "be undone.",
            suggestions=[
                f"Ask the user to explicitly approve deleting job {job_id}, then "
                "call delete_job again with confirm=true."
            ],
        )
    parsed = _parse_job_id(job_id)
    if parsed is None:
        return _invalid_job_id(job_id)
    deleted = await _hub_client().delete_job(str(parsed))
    if not deleted:
        return error_response(
            f"Job {job_id} was not deleted.",
            suggestions=[
                "The job may not exist, may not belong to you, may back a "
                "leaderboard submission, or may be an unfinished hosted job."
            ],
        )
    return fmt({"job_id": str(parsed), "deleted": True})


def register(mcp: Any) -> None:
    for tool in (
        upload_job,
        publish_task,
        publish_dataset,
        download_job,
        set_job_visibility,
        share_job,
        delete_job,
    ):
        mcp.tool()(tool)
