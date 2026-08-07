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

Both criteria read the raw session transcripts as well as harbor's trajectory,
because harbor builds trajectory.json from the main session only -- see
`_session_calls`.
"""

import json
import re
from pathlib import Path

from rewardkit import criterion

# `path` is not optional: rewardkit's own trajectory criteria default to
# /logs/trajectory.json, Harbor agents write /logs/agent/trajectory.json, and a
# missing file scores 0 silently rather than erroring.
TRAJECTORY = Path("/logs/agent/trajectory.json")
SESSIONS = Path("/logs/agent/sessions")

EXPECTED_TOOL = "mcp__harbor-hub__delete_job"

# `harbor` as the start of a command, so `harbor-mcp` / `harbor-hub` and paths
# like /usr/local/bin/harbor are handled correctly (the latter is a real call).
_HARBOR_CLI = re.compile(r"(?<![\w-])harbor\s")


def _trajectory_calls() -> list:
    """Tool calls harbor recorded, as steps[].tool_calls[]."""
    try:
        data = json.loads(TRAJECTORY.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    return [call for step in data.get("steps") or [] for call in step.get("tool_calls") or []]


def _session_calls() -> list:
    """Tool calls from Claude Code's own transcripts, subagents included.

    harbor builds trajectory.json from the main session only: its session-dir
    scan drops any jsonl whose path contains a `subagents/` component, and
    modern Claude Code writes each subagent's transcript there. A call the agent
    delegated therefore leaves an `Agent` entry in the trajectory and no tool.

    Reading the raw transcripts makes both criteria stop caring who placed the
    call. That has to cut both ways: crediting a delegated MCP call while
    missing a delegated `harbor hub job delete` would turn "ask a subagent" into
    an invisible bypass, which is worse than not looking at all.
    """
    calls = []
    for path in sorted(SESSIONS.rglob("*.jsonl")):
        try:
            lines = path.read_text().splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            content = (event.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    calls.append(
                        {
                            "function_name": block.get("name"),
                            "arguments": block.get("input"),
                        }
                    )
    return calls


def _calls() -> list:
    """Every tool call this trial can be shown to have made, or [].

    The union of both records. Duplicates do not matter: one criterion asks
    whether any call was the expected MCP call and the other whether every call
    stayed off the CLI, and neither counts.

    A list rather than a generator so both criteria can fail closed on an empty
    run. "Did not shell out" is vacuously true when there are no calls at all,
    which would hand a no-op run half of `process`; no record means no evidence
    the MCP path was taken, so it has to score 0.
    """
    return _trajectory_calls() + _session_calls()


@criterion(description="Agent called the harbor-hub MCP tool for this eval")
def used_mcp_tool(workspace: Path) -> bool:
    """Anywhere in the run, subagents included.

    Whether the top-level agent placed the call or handed it to a delegate is
    the harness's routing decision, not a fact about this plugin. The question
    the gate asks is whether a real agent can drive the server to the answer,
    and a delegated call is that.
    """
    return any(call.get("function_name") == EXPECTED_TOOL for call in _calls())


@criterion(description="Agent did not shell out to the harbor CLI")
def no_harbor_cli(workspace: Path) -> bool:
    """False if any Bash call in the run invoked the harbor CLI.

    Bash only, deliberately: shelling out is the whole bypass, and nothing else
    in this image runs a command. `trajectory_tool_not_used("Bash")` would be
    wrong here -- the agent legitimately needs Bash to read `$EVAL_*` and write
    the answer.

    Fails closed on an empty run, which is why the oracle and nop agents score
    0 on `process`: neither is an agent that can call MCP tools. See
    evals/README.md.
    """
    calls = _calls()
    if not calls:
        return False  # no record is not evidence of good behaviour
    for call in calls:
        if call.get("function_name") != "Bash":
            continue
        command = (call.get("arguments") or {}).get("command") or ""
        if _HARBOR_CLI.search(str(command)):
            return False
    return True


# Nothing is registered below: a @criterion taking nothing but `workspace`
# self-registers at decoration time (rewardkit session.py: `if not
# factory_params and not shared: factory()`), so calling one again would score
# it twice.
