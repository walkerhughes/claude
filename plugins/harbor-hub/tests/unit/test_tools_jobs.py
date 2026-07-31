import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from harbor.auth.errors import NotAuthenticatedError
from harbor.hub.models import (
    JobOverview,
    JobSummary,
    OverviewJob,
    Page,
    TrialDetail,
    TrialSummary,
)

from harbor_mcp.tools import jobs

JOB_UUID = "1a71e496-98d3-4b6a-9767-ad03e75c5a54"


def make_job(**overrides) -> JobSummary:
    base = dict(
        id="job-1",
        name="nightly-tbench",
        started_at="2026-07-16T00:00:00+00:00",
        finished_at="2026-07-16T01:00:00+00:00",
        n_total_trials=10,
        n_completed_trials=9,
        n_errors=1,
        cost_usd=4.2,
        reward=None,
    )
    base.update(overrides)
    return JobSummary(**base)


def make_trial(**overrides) -> TrialSummary:
    base = dict(
        id="trial-1",
        name="hello-world.1-of-1",
        task_name="hello-world",
        source=None,
        agent_name="claude-code",
        agent_version="2.0.1",
        model_provider="anthropic",
        model_name="claude-opus-4-1",
        reward=1.0,
        error_type=None,
        status="completed",
        hosted_error=None,
        started_at="2026-07-16T00:00:00+00:00",
        finished_at="2026-07-16T00:01:30+00:00",
        input_tokens=100,
        output_tokens=50,
        cache_tokens=0,
        cost_usd=0.12,
        attempt=1,
        n_attempts=1,
        job_id="job-1",
        job_name="nightly-tbench",
    )
    base.update(overrides)
    return TrialSummary(**base)


def make_page(items, **overrides) -> Page:
    base = dict(
        items=items,
        total=len(items),
        page=1,
        page_size=50,
        total_pages=1,
        raw={},
    )
    base.update(overrides)
    return Page(**base)


def make_overview(**overrides) -> JobOverview:
    base = dict(
        jobs=[OverviewJob(id="job-1", name="nightly-tbench")],
        n_total_trials=10,
        n_completed_trials=9,
        n_errors=1,
        n_retries=2,
        n_planned_trials=10,
        input_tokens=1000,
        output_tokens=500,
        cache_tokens=100,
        cost_usd=4.2,
        providers=["anthropic"],
        models=["claude-opus-4-1"],
        evals={"rows": [{"metrics": [{"reward": 0.9}]}]},
        raw={},
    )
    base.update(overrides)
    return JobOverview(**base)


def make_detail(**overrides) -> TrialDetail:
    base = dict(
        id="trial-1",
        trial_name="hello-world.1-of-1",
        task_name="hello-world",
        job_id="job-1",
        job_name="nightly-tbench",
        job_visibility="private",
        source=None,
        agent_name="claude-code",
        agent_version="2.0.1",
        model_provider="anthropic",
        model_name="claude-opus-4-1",
        reward=1.0,
        error_type=None,
        error_message=None,
        trajectory_path="trajectories/trial-1.json",
        started_at="2026-07-16T00:00:00+00:00",
        finished_at="2026-07-16T00:02:00+00:00",
        lock=None,
        raw={"id": "trial-1"},
    )
    base.update(overrides)
    return TrialDetail(**base)


@pytest.fixture
def fake_hub(monkeypatch) -> SimpleNamespace:
    hub = SimpleNamespace(
        list_jobs=AsyncMock(),
        get_job_overview=AsyncMock(),
        get_job_header=AsyncMock(),
        get_job_trials=AsyncMock(),
        get_trial_detail=AsyncMock(),
    )
    monkeypatch.setattr(jobs, "_hub", lambda: hub)
    return hub


@pytest.fixture
def fake_upload_db(monkeypatch) -> SimpleNamespace:
    db = SimpleNamespace(get_job=AsyncMock(), list_trials_for_job=AsyncMock())
    monkeypatch.setattr(jobs, "_upload_db", lambda: db)
    return db


async def test_whoami_happy(monkeypatch):
    monkeypatch.setattr(
        jobs, "resolve_api_key", lambda: ("sk-harbor-abc123_supersecret", "env")
    )
    monkeypatch.setattr(jobs, "require_user_id", AsyncMock(return_value="user-1"))

    raw = await jobs.whoami()
    payload = json.loads(raw)
    assert payload == {
        "authenticated": True,
        "user_id": "user-1",
        "key_source": "env",
        "key_id": "abc123",
    }
    assert "supersecret" not in raw


async def test_whoami_not_authenticated(monkeypatch):
    monkeypatch.setattr(jobs, "resolve_api_key", lambda: None)
    monkeypatch.setattr(
        jobs, "require_user_id", AsyncMock(side_effect=NotAuthenticatedError())
    )

    payload = json.loads(await jobs.whoami())
    assert "Not authenticated" in payload["error"]
    assert payload["suggestions"]


async def test_list_jobs_happy(fake_hub):
    fake_hub.list_jobs.return_value = make_page(
        [make_job()], page_size=20, total=1, total_pages=1
    )

    payload = json.loads(await jobs.list_jobs())
    fake_hub.list_jobs.assert_awaited_once_with(page=1, page_size=20, search=None)
    assert payload["total"] == 1
    assert payload["page"] == 1
    assert payload["total_pages"] == 1
    assert payload["jobs"] == [
        {
            "id": "job-1",
            "name": "nightly-tbench",
            "status": "finished",
            "started_at": "2026-07-16T00:00:00+00:00",
            "finished_at": "2026-07-16T01:00:00+00:00",
            "n_total_trials": 10,
            "n_completed_trials": 9,
            "n_errors": 1,
            "cost_usd": 4.2,
        }
    ]
    assert "note" not in payload


async def test_list_jobs_passes_search(fake_hub):
    fake_hub.list_jobs.return_value = make_page([])

    await jobs.list_jobs(page=2, page_size=5, search="  swe ")
    fake_hub.list_jobs.assert_awaited_once_with(page=2, page_size=5, search="swe")


async def test_get_job_overview_happy(fake_hub):
    fake_hub.get_job_overview.return_value = make_overview()
    fake_hub.get_job_header.return_value = {"id": "job-1", "job_name": "header-name"}

    payload = json.loads(await jobs.get_job_overview("job-1"))
    fake_hub.get_job_overview.assert_awaited_once_with(["job-1"])
    assert payload["job_id"] == "job-1"
    assert payload["name"] == "header-name"
    assert payload["n_total_trials"] == 10
    assert payload["n_retries"] == 2
    assert payload["cost_usd"] == 4.2
    assert payload["reward"] == 0.9
    assert payload["providers"] == ["anthropic"]
    assert payload["models"] == ["claude-opus-4-1"]


async def test_get_job_overview_not_found(fake_hub):
    fake_hub.get_job_overview.return_value = make_overview(jobs=[], evals={})
    fake_hub.get_job_header.return_value = None

    payload = json.loads(await jobs.get_job_overview("missing"))
    assert "not found or not accessible" in payload["error"]
    assert payload["suggestions"]


async def test_get_job_trials_happy(fake_hub):
    failed = make_trial(
        id="trial-2",
        name="hello-world.2-of-2",
        reward=None,
        status="failed",
        hosted_error="OOMKilled",
        cost_usd=None,
        finished_at=None,
    )
    fake_hub.get_job_trials.return_value = make_page([make_trial(), failed])

    payload = json.loads(await jobs.get_job_trials("job-1", failed_only=True))
    fake_hub.get_job_trials.assert_awaited_once_with(
        ["job-1"], page=1, page_size=50, failed_only=True
    )
    assert payload["total"] == 2
    first, second = payload["trials"]
    assert first == {
        "id": "trial-1",
        "name": "hello-world.1-of-1",
        "task": "hello-world",
        "status": "completed",
        "reward": 1.0,
        "cost_usd": 0.12,
        "duration_sec": 90.0,
        "attempt": 1,
        "n_attempts": 1,
    }
    assert second["error_type"] == "OOMKilled"
    assert "duration_sec" not in second
    assert "note" not in payload


async def test_get_job_trials_truncates(fake_hub):
    trials = [make_trial(id=f"trial-{i}") for i in range(120)]
    fake_hub.get_job_trials.return_value = make_page(trials, page_size=200)

    payload = json.loads(await jobs.get_job_trials("job-1", page_size=200))
    assert len(payload["trials"]) == jobs.TRIAL_ROWS_CAP
    assert "100 of 120" in payload["note"]


async def test_get_job_trials_empty_notes(fake_hub):
    fake_hub.get_job_trials.return_value = make_page([], total=0)

    payload = json.loads(await jobs.get_job_trials("job-1"))
    assert payload["trials"] == []
    assert "no trials returned" in payload["note"]


async def test_get_trial_detail_happy(fake_hub):
    fake_hub.get_trial_detail.return_value = make_detail()

    payload = json.loads(await jobs.get_trial_detail("trial-1"))
    fake_hub.get_trial_detail.assert_awaited_once_with("trial-1")
    assert payload["id"] == "trial-1"
    assert payload["task"] == "hello-world"
    assert payload["agent"] == "claude-code"
    assert payload["model"] == "anthropic/claude-opus-4-1"
    assert payload["reward"] == 1.0
    assert payload["duration_sec"] == 120.0
    assert payload["trajectory_path"] == "trajectories/trial-1.json"
    assert "error_type" not in payload


async def test_get_trial_detail_not_found(fake_hub):
    fake_hub.get_trial_detail.return_value = TrialDetail.from_payload(None)

    payload = json.loads(await jobs.get_trial_detail("missing"))
    assert "not found or not accessible" in payload["error"]
    assert payload["suggestions"]


async def test_check_job_upload_happy(fake_upload_db):
    fake_upload_db.get_job.return_value = {
        "id": JOB_UUID,
        "job_name": "nightly-tbench",
        "archive_path": "jobs/x.tar.zst",
        "config": {},
        "started_at": "2026-07-16T00:00:00+00:00",
        "finished_at": "2026-07-16T01:00:00+00:00",
        "n_planned_trials": 3,
    }
    fake_upload_db.list_trials_for_job.return_value = [
        {"id": "t1", "trial_name": "a", "archive_path": "p1", "status": "completed"},
        {"id": "t2", "trial_name": "b", "archive_path": "p2", "status": "completed"},
        {"id": "t3", "trial_name": "c", "archive_path": None, "status": "failed"},
    ]

    payload = json.loads(await jobs.check_job_upload(JOB_UUID))
    fake_upload_db.get_job.assert_awaited_once_with(uuid.UUID(JOB_UUID))
    fake_upload_db.list_trials_for_job.assert_awaited_once_with(uuid.UUID(JOB_UUID))
    assert payload["exists"] is True
    assert payload["job_name"] == "nightly-tbench"
    assert payload["archive_present"] is True
    assert payload["n_planned_trials"] == 3
    assert payload["n_trials_uploaded"] == 3
    assert payload["status_counts"] == {"completed": 2, "failed": 1}
    assert payload["n_trials_missing_archive"] == 1
    assert payload["trials_missing_archive"] == ["c"]


async def test_check_job_upload_not_found(fake_upload_db):
    fake_upload_db.get_job.return_value = None

    payload = json.loads(await jobs.check_job_upload(JOB_UUID))
    assert payload["exists"] is False
    assert "not found or not accessible" in payload["note"]
    fake_upload_db.list_trials_for_job.assert_not_awaited()


async def test_check_job_upload_invalid_uuid(fake_upload_db):
    payload = json.loads(await jobs.check_job_upload("not-a-uuid"))
    assert "must be a UUID" in payload["error"]
    fake_upload_db.get_job.assert_not_awaited()


async def test_check_job_upload_truncates_missing_archives(fake_upload_db):
    fake_upload_db.get_job.return_value = {"id": JOB_UUID, "job_name": "big"}
    fake_upload_db.list_trials_for_job.return_value = [
        {"id": f"t{i}", "trial_name": f"trial-{i}", "archive_path": None}
        for i in range(30)
    ]

    payload = json.loads(await jobs.check_job_upload(JOB_UUID))
    assert payload["n_trials_missing_archive"] == 30
    assert len(payload["trials_missing_archive"]) == jobs.MISSING_ARCHIVE_SAMPLE_CAP
    assert "20 of 30" in payload["note"]


def test_register_registers_all_job_tools():
    registered: list[str] = []

    class FakeMCP:
        def tool(self):
            def decorator(fn):
                registered.append(fn.__name__)
                return fn

            return decorator

    jobs.register(FakeMCP())
    assert registered == [
        "whoami",
        "list_jobs",
        "get_job_overview",
        "get_job_trials",
        "get_trial_detail",
        "check_job_upload",
    ]
