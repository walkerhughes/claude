"""Harbor hub MCP server: stdio entry point."""

from mcp.server.fastmcp import FastMCP

from harbor_mcp.tools import register_all

INSTRUCTIONS = """Tools for the Harbor hub (harborframework.com): inspect evaluation jobs and
trials, verify uploads, resolve published tasks/datasets, and (when enabled)
publish and manage hub data.

Authenticate with `harbor auth login`, which stores a key scoped to the logged-in
user in ~/.harbor/credentials.json; harbor reads it directly.

Start with whoami to verify credentials. Find job ids with list_jobs, then
drill down with get_job_overview, get_job_trials, get_trial_detail, or
check_job_upload. Write tools (upload_job, publish_task, publish_dataset,
download_job, set_job_visibility, share_job, delete_job) require
HARBOR_MCP_ENABLE_WRITES=true in the server environment; delete_job is
permanent and additionally requires confirm=true after explicit user approval."""

mcp = FastMCP("harbor-hub", instructions=INSTRUCTIONS)
register_all(mcp)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
