#!/usr/bin/env python3
"""Score every eval's real `process` criteria against synthetic runs.

    python3 evals/validate_process_local.py

No Harbor, no hub, no API key, no Docker, no model. `harbor run -a oracle`
cannot answer the question this asks: the oracle takes the intended route by
construction, so it proves an eval is solvable and says nothing about whether a
bypass would be caught. These rows are the bypasses.

rewardkit is not importable on macOS (its litellm dependency wants a newer
rustc than ships there), so it is stubbed to a no-op decorator and the real
check.py is loaded from disk. That keeps the file under test the same one that
will really grade a gate run, minus the scoring layer -- the criteria bodies,
which is where the logic lives.

ponytail: asserts and a table, no pytest. Add a framework when there is a
second thing to test.
"""

import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path

EVALS = Path(__file__).resolve().parent

# Each eval's expected MCP tool, and a CLI bypass that would produce the same
# answer without it.
CASES = {
    "read-job": (
        "mcp__harbor-hub__get_job_overview",
        "harbor hub job show abc123 --json",
    ),
    "delete-job": ("mcp__harbor-hub__delete_job", "harbor hub job delete abc123"),
    "check-published-task": (
        "mcp__harbor-hub__check_task_published",
        "harbor download org/name@1 -o /tmp/x",
    ),
}


def _stub_rewardkit() -> None:
    """Make `from rewardkit import criterion` a no-op passthrough."""

    def criterion(*args, **kwargs):
        if args and callable(args[0]):
            return args[0]
        return lambda fn: fn

    module = types.ModuleType("rewardkit")
    module.criterion = criterion
    sys.modules["rewardkit"] = module


def _load(eval_name: str):
    path = EVALS / eval_name / "tests" / "process" / "check.py"
    spec = importlib.util.spec_from_file_location(f"check_{eval_name.replace('-', '_')}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _trajectory(*calls: dict) -> dict:
    return {"steps": [{"tool_calls": list(calls)}]}


def _call(name: str, **arguments) -> dict:
    return {"function_name": name, "arguments": arguments}


def _session_line(name: str, **arguments) -> str:
    """One Claude Code transcript event carrying a tool_use block."""
    return json.dumps({"message": {"content": [{"type": "tool_use", "name": name, "input": arguments}]}})


def _score(module, root: Path, trajectory: dict | None, subagent_lines: list[str]) -> tuple[bool, bool]:
    """Point the module's paths at a temp tree and run both criteria."""
    module.TRAJECTORY = root / "trajectory.json"
    module.SESSIONS = root / "sessions"
    if trajectory is not None:
        module.TRAJECTORY.write_text(json.dumps(trajectory))
    if subagent_lines:
        # Where Claude Code writes a delegate's transcript, and the component
        # harbor's session scan drops when it builds trajectory.json.
        subagents = module.SESSIONS / "subagents"
        subagents.mkdir(parents=True)
        (subagents / "delegate.jsonl").write_text("\n".join(subagent_lines) + "\n")
    return module.used_mcp_tool(root), module.no_harbor_cli(root)


def main() -> int:
    _stub_rewardkit()
    failures = []

    for eval_name, (tool, cli) in CASES.items():
        module = _load(eval_name)
        assert module.EXPECTED_TOOL == tool, f"{eval_name}: EXPECTED_TOOL is {module.EXPECTED_TOOL!r}"

        agent_only = _trajectory(_call("Agent", prompt="ask a delegate"))

        # case, trajectory, subagent transcript lines, expected (used_mcp, no_cli)
        rows = [
            ("solved", _trajectory(_call(tool, job_id="abc123")), [], (True, True)),
            ("empty", None, [], (False, False)),
            ("bypassed", _trajectory(_call("Bash", command=cli)), [], (False, False)),
            (
                "fell-back",
                _trajectory(_call(tool, job_id="abc"), _call("Bash", command=cli)),
                [],
                (True, False),
            ),
            (
                "delegated",
                agent_only,
                [_session_line(tool, job_id="abc123")],
                (True, True),
            ),
            (
                "delegated-bypass",
                agent_only,
                [_session_line("Bash", command=cli)],
                (False, False),
            ),
            (
                "benign-bash",
                _trajectory(
                    _call(tool, job_id="abc"),
                    _call("Bash", command="echo 1 > answer.txt"),
                ),
                [],
                (True, True),
            ),
        ]

        for case, trajectory, lines, expected in rows:
            with tempfile.TemporaryDirectory() as tmp:
                got = _score(module, Path(tmp), trajectory, lines)
            mark = "ok" if got == expected else "FAIL"
            if got != expected:
                failures.append(f"{eval_name}/{case}: expected {expected}, got {got}")
            print(f"  {mark:4} {eval_name:22} {case:18} used_mcp={got[0]!s:5} no_cli={got[1]!s:5}")

    print()
    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1
    print(f"process criteria ok: {len(CASES) * 7} checks across {len(CASES)} evals")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
