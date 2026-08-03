"""`process` reward: the delete went through the harbor-hub MCP server.

The `outcome` reward only sees /app/answer.txt and the hub, and the harbor CLI
is on PATH in this image (the oracle and the verifier both need it). So an agent
that never touches the MCP -- or one that calls it, gets an error, and quietly
falls back to `harbor hub job delete` -- still leaves the job deleted.
That is exactly the regression this eval exists to catch, so grade the
trajectory too.

The instruction deliberately does NOT name the tool. Naming it would test the
agent's reading comprehension, not the plugin: the whole point of the plugin is
that its tool descriptions and server instructions do the routing, so the
caller does not have to. If a run fails here, the bug is upstream in the tool
description or the server instructions, not in this eval -- fix it there rather
than hinting in instruction.md.

Claude Code names MCP tools `mcp__<server>__<tool>`; `<server>` is the
`[[environment.mcp_servers]]` name from task.toml, written verbatim into the
agent's config.

`path` is not optional: rewardkit's trajectory criteria default to
/logs/trajectory.json, Harbor agents write /logs/agent/trajectory.json, and a
missing file scores 0 silently rather than erroring.
"""

import json
import re
from pathlib import Path

from rewardkit import criteria, criterion

TRAJECTORY = "/logs/agent/trajectory.json"

# `harbor` as the start of a command, so `harbor-mcp` / `harbor-hub` and paths
# like /usr/local/bin/harbor are handled correctly (the latter is a real call).
_HARBOR_CLI = re.compile(r"(?<![\w-])harbor\s")


@criterion(description="Agent did not shell out to the harbor CLI")
def no_harbor_cli(workspace: Path) -> bool:
    """False if any Bash tool call in the trajectory invoked the harbor CLI.

    Fails closed: no trajectory means no evidence the MCP path was used. That
    is why the oracle and nop agents score 0 on `process` -- neither is an
    agent that can call MCP tools. See evals/README.md.
    """
    try:
        data = json.loads(Path(TRAJECTORY).read_text())
    except (OSError, json.JSONDecodeError):
        return False

    for step in data.get("steps") or []:
        for call in step.get("tool_calls") or []:
            if call.get("function_name") != "Bash":
                continue
            command = (call.get("arguments") or {}).get("command") or ""
            if _HARBOR_CLI.search(str(command)):
                return False
    return True


criteria.trajectory_tool_used("mcp__harbor-hub__delete_job", path=TRAJECTORY)
criteria.no_harbor_cli()
