#!/usr/bin/env python3
"""Behavioural eval for the parallel-agent-isolation skill.

Each case runs headless Claude Code in a throwaway workspace that contains only
this skill, and checks two things: whether the skill loaded on its own, and
whether the answer resolves the shared-resource problem instead of dispatching
naively. A rubric is graded by a second, tool-less Claude Code call returning a
structured verdict.

Both halves matter. A skill that never loads is inert whatever its body says,
and a skill that loads for every parallel dispatch is noise, so one case must
not trigger it at all.

Usage: python3 run_evals.py [case-name ...]
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILL_NAME = SKILL_DIR.name
CASES_DIR = Path(__file__).resolve().parent / "cases"

MODEL = os.environ.get("EVAL_MODEL", "sonnet")
BUDGET_USD = os.environ.get("EVAL_MAX_BUDGET_USD", "1.00")
TIMEOUT_SEC = int(os.environ.get("EVAL_TIMEOUT_SEC", "600"))
# Whether a description triggers is a sampled behaviour, so one run of a case
# says little. Every run of a case must hold for the case to pass.
RUNS = int(os.environ.get("EVAL_RUNS", "3"))

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["pass", "fail"]},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "reason"],
}


class EvalError(RuntimeError):
    pass


def run_claude(prompt: str, cwd: Path, extra: list[str]) -> list[dict]:
    """Run headless Claude Code and return the parsed stream-json events."""
    command = [
        "claude",
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        MODEL,
        # Only the project's own .claude/ is loaded, so a personal skill on the
        # developer's machine cannot stand in for the one under test.
        "--setting-sources",
        "project",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--max-budget-usd",
        BUDGET_USD,
        *extra,
    ]
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT_SEC)
    if result.returncode != 0:
        raise EvalError(f"claude exited {result.returncode}: {result.stderr.strip()[:500]}")

    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    if not events:
        raise EvalError("claude produced no output")
    return events


def final_text(events: list[dict]) -> str:
    for event in reversed(events):
        if event.get("type") == "result":
            if event.get("is_error"):
                raise EvalError(
                    f"claude reported an error result: {str(event.get('result'))[:300]}"
                )
            return event.get("result") or ""
    raise EvalError("no result event in the stream")


def total_cost(events: list[dict]) -> float:
    for event in reversed(events):
        if event.get("type") == "result":
            return float(event.get("total_cost_usd") or 0.0)
    return 0.0


def skill_was_loaded(events: list[dict]) -> bool:
    for event in events:
        if event.get("type") != "assistant":
            continue
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "tool_use" and block.get("name") == "Skill":
                if (block.get("input") or {}).get("skill") == SKILL_NAME:
                    return True
    return False


def judge(rubric: list[str], answer: str, workspace: Path) -> tuple[bool, str]:
    """Grade an answer against a rubric with a tool-less Claude Code call."""
    criteria = "\n".join(f"{i}. {line}" for i, line in enumerate(rubric, start=1))
    prompt = (
        "You are grading one answer against fixed criteria. Judge only what the answer says.\n"
        "Return verdict 'pass' only if every criterion is met, otherwise 'fail'.\n"
        "Keep reason to one sentence, and quote the answer where it decides the verdict.\n\n"
        f"CRITERIA\n{criteria}\n\nANSWER\n{answer}\n"
    )
    events = run_claude(
        prompt,
        workspace,
        ["--tools", "", "--json-schema", json.dumps(VERDICT_SCHEMA)],
    )
    try:
        parsed = json.loads(final_text(events))
    except json.JSONDecodeError as exc:
        raise EvalError(f"judge did not return the verdict schema: {exc}") from exc
    # The judge occasionally trails a stray closing tag after its reason.
    reason = re.sub(r"(\s*</[a-z_]+>)+\s*$", "", " ".join(parsed["reason"].split()))
    return parsed["verdict"] == "pass", reason


def run_case(case: Path, workspace: Path, judge_workspace: Path) -> tuple[bool, str, float]:
    """Run one case RUNS times. Every run must hold, so one lucky pass is not a pass."""
    spec = json.loads((case / "case.json").read_text())
    prompt = (case / "prompt.md").read_text()
    cost = 0.0

    for attempt in range(1, RUNS + 1):
        events = run_claude(prompt, workspace, ["--tools", "Skill"])
        cost += total_cost(events)

        loaded = skill_was_loaded(events)
        if loaded != spec["expect_skill"]:
            want = "load" if spec["expect_skill"] else "stay out of"
            return False, f"run {attempt}/{RUNS}: the skill did not {want} this scenario", cost

        if not spec.get("rubric"):
            continue

        passed, reason = judge(spec["rubric"], final_text(events), judge_workspace)
        if not passed:
            return False, f"run {attempt}/{RUNS}: {reason}", cost

    return True, f"{RUNS}/{RUNS} runs held", cost


def main() -> int:
    if not shutil.which("claude"):
        print("claude is not on PATH; install Claude Code to run these evals.", file=sys.stderr)
        return 1

    wanted = set(sys.argv[1:])
    cases = sorted(
        p for p in CASES_DIR.iterdir() if p.is_dir() and (not wanted or p.name in wanted)
    )
    if not cases:
        print(f"no cases matched {sorted(wanted)}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix=f"{SKILL_NAME}-evals-") as tmp:
        root = Path(tmp)
        # The agent workspace holds this skill and nothing else, so a load is
        # attributable to this skill's description rather than to the repository.
        workspace = root / "workspace"
        shutil.copytree(
            SKILL_DIR,
            workspace / ".claude" / "skills" / SKILL_NAME,
            ignore=shutil.ignore_patterns("evals"),
        )
        # The judge gets an empty workspace: it must not see the skill it grades against.
        judge_workspace = root / "judge"
        judge_workspace.mkdir()

        failed: list[str] = []
        spent = 0.0
        for case in cases:
            try:
                passed, reason, cost = run_case(case, workspace, judge_workspace)
            except (EvalError, subprocess.TimeoutExpired) as exc:
                passed, reason, cost = False, str(exc), 0.0
            spent += cost
            print(f"{'PASS' if passed else 'FAIL'} {case.name}: {reason}", flush=True)
            if not passed:
                failed.append(case.name)

    print(f"\n{len(cases) - len(failed)}/{len(cases)} cases passed, ${spent:.2f} spent")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
