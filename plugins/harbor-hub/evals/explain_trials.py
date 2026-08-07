#!/usr/bin/env python3
"""Say which trial scored what, and what the agent actually did.

The gate used to dump every trial's verifier output with `cat <job>/*/verifier/
test-stdout.txt`, which prints one anonymous pair of numbers per eval:

    outcome: 1.0
    process: 0.5

That says an eval lost `process` and nothing about which one, let alone why.
Recovering it meant downloading the CI artifact, which needs credentials the
person reading the log may not have and which expires after seven days.

So this prints the trial name with its rewards, and for any trial that did not
score a perfect `process`, the tool calls it made. `process` is entirely a
function of that list -- whether an `mcp__harbor-hub__*` call is in it, and
whether anything else went round the server -- so the list is the diagnosis.

    python3 explain_trials.py <job-dir>

Deliberately does not re-implement the bypass regex. Duplicating it here would
give the log a second opinion that could drift from the checks, and the raw
calls are what a reader needs anyway.
"""

import json
import sys
from pathlib import Path

MCP_PREFIX = "mcp__harbor-hub__"
ARG_WIDTH = 160


def _rewards(trial: Path) -> dict[str, float]:
    """The trial's rewards, read from whatever the verifier left behind.

    rewardkit writes reward.json; its stdout carries the same numbers as
    `name: value` lines. Harbor's layout for these has moved before, so both are
    tried rather than pinning one path.
    """
    for path in sorted(trial.rglob("reward.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        found = {k: float(v) for k, v in data.items() if isinstance(v, int | float)}
        if found:
            return found

    found = {}
    for path in sorted(trial.rglob("test-stdout.txt")):
        try:
            text = path.read_text()
        except OSError:
            continue
        for line in text.splitlines():
            name, _, value = line.partition(":")
            try:
                found[name.strip()] = float(value)
            except ValueError:
                continue
    return found


def _calls(trial: Path) -> list[tuple[str, str]]:
    """(tool name, arguments) for every call in the trial's trajectory."""
    for path in sorted(trial.rglob("trajectory.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        steps = data.get("steps") or []
        return [
            (
                str(call.get("function_name") or "?"),
                json.dumps(call.get("arguments") or {}),
            )
            for step in steps
            for call in step.get("tool_calls") or []
        ]
    return []


def explain(job_dir: Path) -> None:
    trials = sorted(p for p in job_dir.iterdir() if p.is_dir())
    if not trials:
        print(f"no trial directories under {job_dir}")
        return

    for trial in trials:
        rewards = _rewards(trial)
        if not rewards:
            continue
        summary = ", ".join(f"{name}={value}" for name, value in sorted(rewards.items()))
        print(f"\n== {trial.name}: {summary}")

        if rewards.get("process", 0.0) >= 1.0:
            continue

        calls = _calls(trial)
        if not calls:
            print("   no trajectory recorded, so `process` fails closed at 0")
            continue
        mcp = sum(1 for name, _ in calls if name.startswith(MCP_PREFIX))
        print(f"   {len(calls)} tool call(s), {mcp} through the MCP server:")
        for name, args in calls:
            marker = "  " if name.startswith(MCP_PREFIX) else "! "
            print(f"   {marker}{name} {args[:ARG_WIDTH]}")


if __name__ == "__main__":
    explain(Path(sys.argv[1]))
