"""Harbor hub MCP server: stdio entry point."""

from mcp.server.fastmcp import FastMCP

from harbor_mcp.tools import register_all

INSTRUCTIONS = """Tools for the Harbor hub (harborframework.com): inspect evaluation jobs and
trials, verify uploads, resolve published tasks/datasets, and (when enabled)
publish and manage hub data.

These tools are the supported way to reach the hub from here. Prefer them over
shelling out to the `harbor` CLI or calling the hub's HTTP API directly, even
where the CLI happens to be installed: the tools return compact, already-shaped
results, and an answer one of them gives you is authoritative -- it does not
need confirming a second way.

Authenticate with `harbor auth login`, which stores a key scoped to the logged-in
user in ~/.harbor/credentials.json; harbor reads it directly.

Which tool, by what you already have:
- no job id, need to find one: list_jobs (optionally filtered by name)
- a job id, want how the job did overall: get_job_overview -- its `reward` is
  the mean across the job's trials, already aggregated
- a job id, want individual trials: get_job_trials, then get_trial_detail
- a job id, checking an upload landed: check_job_upload
- a task reference like org/name@ref: check_task_published
- a dataset reference: resolve_dataset
- credentials in doubt: whoami

Write tools (upload_job, publish_task, publish_dataset, download_job,
set_job_visibility, share_job, delete_job) require HARBOR_MCP_ENABLE_WRITES=true
in the server environment; delete_job is permanent and additionally requires
confirm=true after explicit user approval."""

mcp = FastMCP("harbor-hub", instructions=INSTRUCTIONS)
register_all(mcp)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
