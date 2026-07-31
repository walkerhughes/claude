"""Read tools over the Harbor hub: identity, jobs, trials, and upload checks."""

import uuid
from collections import Counter
from datetime import datetime
from functools import cache
from typing import Any

from harbor.auth.client import require_user_id
from harbor.auth.credentials import parse_key_id, resolve_api_key
from harbor.hub.client import HubClient
from harbor.hub.models import JobSummary, TrialSummary
from harbor.upload.db_client import UploadDB

from harbor_mcp.infra.errors import error_response, guarded_tool
from harbor_mcp.tools.base import compact, fmt, truncate

JOB_ROWS_CAP = 100
TRIAL_ROWS_CAP = 100
MISSING_ARCHIVE_SAMPLE_CAP = 20


@cache
def _hub() -> HubClient:
    """One HubClient per process: it caches its auth check across calls."""
    return HubClient()


@cache
def _upload_db() -> UploadDB:
    return UploadDB()


def _parse_uuid(value: str, param: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (AttributeError, TypeError, ValueError):
        raise ValueError(
            f"{param} must be a UUID, got {value!r}. "
            "Use list_jobs or get_job_trials to find valid ids."
        ) from None


def _duration_sec(started_at: str | None, finished_at: str | None) -> float | None:
    if not started_at or not finished_at:
        return None
    try:
        delta = datetime.fromisoformat(finished_at) - datetime.fromisoformat(started_at)
    except (TypeError, ValueError):
        return None
    return round(delta.total_seconds(), 3)


def _job_row(job: JobSummary) -> dict[str, Any]:
    return compact(
        {
            "id": job.id,
            "name": job.name,
            "status": job.status,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "n_total_trials": job.n_total_trials,
            "n_completed_trials": job.n_completed_trials,
            "n_errors": job.n_errors,
            "cost_usd": job.cost_usd,
            "reward": job.reward,
        }
    )


def _trial_row(trial: TrialSummary) -> dict[str, Any]:
    return compact(
        {
            "id": trial.id,
            "name": trial.name,
            "task": trial.task_name or None,
            "status": trial.status,
            "reward": trial.reward,
            "error_type": trial.error_display,
            "cost_usd": trial.cost_usd,
            "duration_sec": _duration_sec(trial.started_at, trial.finished_at),
            "attempt": trial.attempt,
            "n_attempts": trial.n_attempts,
        }
    )


@guarded_tool
async def whoami() -> str:
    """Report the authenticated Harbor hub identity: the user id, where the
    credential came from (the HARBOR_API_KEY env var or the `harbor auth login`
    file), and the public key id. Never returns the key itself. Call this first
    to verify credentials before using list_jobs, get_job_trials, or the
    registry tools."""
    creds = resolve_api_key()
    user_id = await require_user_id()
    payload: dict[str, Any] = {"authenticated": True, "user_id": user_id}
    if creds is not None:
        key, source = creds
        payload["key_source"] = source
        payload["key_id"] = parse_key_id(key)
    return fmt(compact(payload))


@guarded_tool
async def list_jobs(page: int = 1, page_size: int = 20, search: str = "") -> str:
    """List the Harbor hub jobs visible to your account, with trial counts,
    errors, cost, and reward. An empty `search` means no name filter. Use the
    returned job ids with get_job_overview, get_job_trials, or
    check_job_upload."""
    result = await _hub().list_jobs(
        page=page, page_size=page_size, search=search.strip() or None
    )
    rows, note = truncate([_job_row(job) for job in result.items], JOB_ROWS_CAP)
    return fmt(
        compact(
            {
                "jobs": rows,
                "page": result.page,
                "page_size": result.page_size,
                "total": result.total,
                "total_pages": result.total_pages,
                "note": note,
            }
        )
    )


@guarded_tool
async def get_job_overview(job_id: str) -> str:
    """Roll up one hub job: trial counts, retries, token usage, cost, reward,
    and the providers/models involved. Find job ids with list_jobs; drill into
    individual trials with get_job_trials."""
    hub = _hub()
    overview = await hub.get_job_overview([job_id])
    header = await hub.get_job_header(job_id)
    if overview.is_empty and header is None:
        return error_response(
            f"Job not found or not accessible: {job_id}",
            suggestions=["Use list_jobs to find jobs visible to your account."],
        )
    name = (header or {}).get("job_name") or (
        overview.jobs[0].name if overview.jobs else None
    )
    return fmt(
        compact(
            {
                "job_id": job_id,
                "name": name,
                "n_total_trials": overview.n_total_trials,
                "n_completed_trials": overview.n_completed_trials,
                "n_errors": overview.n_errors,
                "n_retries": overview.n_retries,
                "n_planned_trials": overview.n_planned_trials,
                "input_tokens": overview.input_tokens,
                "output_tokens": overview.output_tokens,
                "cache_tokens": overview.cache_tokens,
                "cost_usd": overview.cost_usd,
                "reward": overview.reward,
                "providers": overview.providers or None,
                "models": overview.models or None,
            }
        )
    )


@guarded_tool
async def get_job_trials(
    job_id: str, page: int = 1, page_size: int = 50, failed_only: bool = False
) -> str:
    """List a hub job's trials (latest attempt per trial) with task, status,
    reward, error, cost, and duration. Set failed_only=True to see only errored
    trials. Get job ids from list_jobs; pass a returned trial id to
    get_trial_detail for one trial's full record."""
    result = await _hub().get_job_trials(
        [job_id], page=page, page_size=page_size, failed_only=failed_only
    )
    rows, note = truncate([_trial_row(t) for t in result.items], TRIAL_ROWS_CAP)
    if result.total == 0:
        note = "no trials returned; verify the job id via list_jobs or check_job_upload"
    return fmt(
        compact(
            {
                "trials": rows,
                "page": result.page,
                "page_size": result.page_size,
                "total": result.total,
                "total_pages": result.total_pages,
                "note": note,
            }
        )
    )


@guarded_tool
async def get_trial_detail(trial_id: str) -> str:
    """Fetch one trial's full record from the hub: task, agent, model, reward,
    error type and message, timings, and trajectory path. Get trial ids from
    get_job_trials."""
    detail = await _hub().get_trial_detail(trial_id)
    if detail.is_empty:
        return error_response(
            f"Trial not found or not accessible: {trial_id}",
            suggestions=["Use get_job_trials to list a job's trial ids."],
        )
    return fmt(
        compact(
            {
                "id": detail.id,
                "name": detail.trial_name,
                "task": detail.task_name,
                "job_id": detail.job_id,
                "job_name": detail.job_name,
                "agent": detail.agent_name,
                "agent_version": detail.agent_version,
                "model": detail.model,
                "reward": detail.reward,
                "error_type": detail.error_type,
                "error_message": detail.error_message,
                "started_at": detail.started_at,
                "finished_at": detail.finished_at,
                "duration_sec": _duration_sec(detail.started_at, detail.finished_at),
                "trajectory_path": detail.trajectory_path,
            }
        )
    )


@guarded_tool
async def check_job_upload(job_id: str) -> str:
    """Verify a job upload on the Harbor hub: whether the job row exists, if
    its archive is present, planned vs uploaded trial counts, per-status
    counts, and which trials are missing archives. Use after `harbor jobs
    upload` or when hub numbers look off; get job ids from list_jobs."""
    parsed = _parse_uuid(job_id, "job_id")
    db = _upload_db()
    job = await db.get_job(parsed)
    if job is None:
        return fmt(
            {
                "exists": False,
                "job_id": job_id,
                "note": (
                    "job not found or not accessible; rows hidden by "
                    "permissions look identical to missing rows"
                ),
            }
        )
    trials = await db.list_trials_for_job(parsed)
    status_counts = Counter(str(t.get("status") or "unknown") for t in trials)
    missing = [
        t.get("trial_name") or str(t.get("id"))
        for t in trials
        if not t.get("archive_path")
    ]
    missing_sample, note = truncate(missing, MISSING_ARCHIVE_SAMPLE_CAP)
    return fmt(
        compact(
            {
                "exists": True,
                "job_id": job_id,
                "job_name": job.get("job_name"),
                "archive_present": bool(job.get("archive_path")),
                "started_at": job.get("started_at"),
                "finished_at": job.get("finished_at"),
                "n_planned_trials": job.get("n_planned_trials"),
                "n_trials_uploaded": len(trials),
                "status_counts": dict(status_counts),
                "n_trials_missing_archive": len(missing),
                "trials_missing_archive": missing_sample or None,
                "note": note,
            }
        )
    )


def register(mcp: Any) -> None:
    for tool in (
        whoami,
        list_jobs,
        get_job_overview,
        get_job_trials,
        get_trial_detail,
        check_job_upload,
    ):
        mcp.tool()(tool)
