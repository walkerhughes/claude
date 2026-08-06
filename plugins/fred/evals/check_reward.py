#!/usr/bin/env python3
"""Gate a harbor ``result.json`` on its rewards.

``harbor run`` exits 0 whatever the reward, so the gate has to inspect the job
result itself. Every fred task reports one reward in [0, 1], so the mean
over a task is its pass rate across attempts.

    python3 check_reward.py <result.json> <name>                 # every reward 1.0
    python3 check_reward.py <result.json> <name> --min-mean 0.9  # allow some slack
    python3 check_reward.py <result.json> <name> --only outcome  # one reward only
    python3 check_reward.py --selftest

Each task reports two rewards, ``outcome`` and ``process`` (see evals/README.md).
``--only`` restricts the gate to one of them, which is how the local validator
holds the oracle to ``outcome``: the oracle is a shell script, not an agent, so
it cannot call MCP tools and cannot score on ``process``.

``--min-mean`` exists because this gate drives a real agent over 10 tasks, not
3. A single flaky task should not be indistinguishable from a broken server,
but the threshold is an explicit number in the workflow rather than a silent
default, so loosening it is a visible decision.
"""

import json
import sys
from pathlib import Path


def rewards(stats: dict, only: str | None = None) -> tuple[list | None, str]:
    """Every reward in the run, or (None, reason) if it did not complete cleanly.

    A task with one reward reports it under the metric name ({"mean": 1.0}); a
    task with several reports them under the reward names ({"outcome": 1.0,
    "process": 1.0}). `only` filters to one of those names.
    """
    if stats.get("n_errored_trials") or not stats.get("n_completed_trials"):
        return None, f"run did not complete cleanly (stats={stats})"
    found = [
        value
        for eval_stats in stats.get("evals", {}).values()
        for metric in eval_stats.get("metrics", [])
        for name, value in metric.items()
        if only is None or name == only
    ]
    if not found:
        return None, f"no {only or ''} rewards reported".replace("  ", " ")
    return found, ""


def gate(stats: dict, min_mean: float = 1.0, only: str | None = None) -> tuple[bool, str]:
    found, reason = rewards(stats, only)
    if found is None:
        return False, reason
    mean = sum(found) / len(found)
    failed = [r for r in found if r < min_mean]
    n = stats["n_completed_trials"]
    if min_mean >= 1.0 and failed:
        return False, f"reward not perfect (mean={mean:.3f}, rewards={found})"
    if mean < min_mean:
        return False, f"mean reward {mean:.3f} below threshold {min_mean} (rewards={found})"
    # `found` counts reward values, not tasks: harbor aggregates every trial into one
    # mean per reward name, so a clean 10-task run reports two. Calling that "2 task(s)"
    # reads like eight tasks went missing at exactly the moment someone is looking for
    # a reason the gate failed.
    return True, f"mean reward {mean:.3f} over {n} trial(s), {len(found)} reward(s)"


def _selftest() -> None:
    ok = {"n_completed_trials": 2, "evals": {"a": {"metrics": [{"mean": 1.0}]}}}
    assert gate(ok)[0]
    assert not gate({**ok, "evals": {"a": {"metrics": [{"mean": 0.0}]}}})[0]
    assert not gate({**ok, "n_errored_trials": 1})[0]
    assert not gate({"n_completed_trials": 0, "evals": {}})[0]
    assert not gate({"n_completed_trials": 1, "evals": {}})[0]

    mixed = {
        "n_completed_trials": 2,
        "evals": {"a": {"metrics": [{"mean": 1.0}]}, "b": {"metrics": [{"mean": 0.0}]}},
    }
    assert not gate(mixed)[0], "one zero must fail a perfect gate"
    assert not gate(mixed, min_mean=0.9)[0], "mean 0.5 is below 0.9"
    assert gate(mixed, min_mean=0.5)[0], "mean 0.5 meets a 0.5 threshold"

    # Two named rewards per task. The oracle solves the answer but cannot call
    # MCP tools, so it is outcome=1, process=0 and only `--only outcome` passes.
    split = {
        "n_completed_trials": 1,
        "evals": {"a": {"metrics": [{"outcome": 1.0, "process": 0.0}]}},
    }
    assert not gate(split)[0], "a zero process reward must fail the full gate"
    assert gate(split, only="outcome")[0]
    assert not gate(split, only="process")[0]
    assert rewards(split, only="nope")[0] is None, "unknown reward name -> None"
    print("check_reward selftest ok")


def main(argv: list[str]) -> int:
    if argv[1:2] == ["--selftest"]:
        _selftest()
        return 0
    result_path, name = argv[1], argv[2]
    min_mean = 1.0
    if "--min-mean" in argv:
        min_mean = float(argv[argv.index("--min-mean") + 1])
    try:
        stats = json.loads(Path(result_path).read_text()).get("stats", {})
    except FileNotFoundError:
        print(f"{name}: no result.json at {result_path}", file=sys.stderr)
        return 1
    only = argv[argv.index("--only") + 1] if "--only" in argv else None
    ok, msg = gate(stats, min_mean, only)
    print(f"{name}: {msg}", file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
