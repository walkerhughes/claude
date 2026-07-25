"""Harbor hub MCP server: stdio entry point."""

import logging
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from harbor_mcp.tools import register_all

logger = logging.getLogger(__name__)

# ponytail: cwd plus three parents, not a walk to the filesystem root. Covers a
# .env beside the project the agent is working in, or one level up in a
# monorepo. Deepen if someone nests deeper than that.
DOTENV_SEARCH_DEPTH = 3

INSTRUCTIONS = """Tools for the Harbor hub (harborframework.com): inspect evaluation jobs and
trials, verify uploads, resolve published tasks/datasets, and (when enabled)
publish and manage hub data.

Start with whoami to verify credentials. Find job ids with list_jobs, then
drill down with get_job_overview, get_job_trials, get_trial_detail, or
check_job_upload. Write tools (upload_job, publish_task, publish_dataset,
download_job, set_job_visibility, share_job, delete_job) require
HARBOR_MCP_ENABLE_WRITES=true in the server environment; delete_job is
permanent and additionally requires confirm=true after explicit user approval."""

mcp = FastMCP("harbor-hub", instructions=INSTRUCTIONS)
register_all(mcp)


def load_dotenv(start: Path | None = None) -> Path | None:
    """Load the nearest `.env` into os.environ; return the file used, if any.

    Credential precedence, highest first:

    1. A variable already in the environment (the MCP client's config, or the
       user's shell). Never overwritten here.
    2. `KEY=value` lines in the nearest `.env`.
    3. `~/.harbor/credentials.json` from `harbor auth login`, which harbor
       falls back to on its own when HARBOR_API_KEY is unset or blank.

    A missing `.env` is therefore the normal case for anyone who authenticated
    with the CLI, not an error.
    """
    base = (start or Path.cwd()).resolve()
    for directory in (base, *base.parents[:DOTENV_SEARCH_DEPTH]):
        env_file = directory / ".env"
        if not env_file.is_file():
            continue
        try:
            text = env_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # An unreadable .env must not take the server down: harbor can still
            # authenticate from the env var or the credentials file.
            logger.warning("could not read %s; ignoring it", env_file, exc_info=True)
            return None
        for line in text.splitlines():
            entry = line.strip().removeprefix("export ").strip()
            if not entry or entry.startswith("#") or "=" not in entry:
                continue
            key, _, value = entry.partition("=")
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = value.strip().strip("\"'")
        return env_file
    return None


def main() -> None:
    # Before mcp.run, and never at import time: importing this module must not
    # mutate the environment out from under the test suite.
    load_dotenv()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
