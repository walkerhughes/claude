#!/usr/bin/env python3
"""Gate a harbor ``result.json`` on its rewards.

``harbor run`` exits 0 whatever the reward, so the gate has to inspect the job
result itself. Every tastytrade task reports one reward in [0, 1], so the mean
over a task is its pass rate across attempts.

    python3 check_reward.py <result.json> <name>                # every reward 1.0
    python3 check_reward.py <result.json> <name> --min-mean 0.9 # allow some slack
    python3 check_reward.py --selftest

``--min-mean`` exists because this gate drives a real agent over 13 tasks, not
3. A single flaky task should not be indistinguishable from a broken server,
but the threshold is an explicit number in the workflow rather than a silent
default, so loosening it is a visible decision.
"""

import json
import sys
from pathlib import Path


def rewards(stats: dict) -> tuple[list | None, str]:
    """Every reward in the run, or (None, reason) if it did not complete cleanly."""
    if stats.get("n_errored_trials") or not stats.get("n_completed_trials"):
        return None, f"run did not complete cleanly (stats={stats})"
    found = [
        value
        for eval_stats in stats.get("evals", {}).values()
        for metric in eval_stats.get("metrics", [])
        for value in metric.values()
    ]
    if not found:
        return None, "no rewards reported"
    return found, ""


def gate(stats: dict, min_mean: float = 1.0) -> tuple[bool, str]:
    found, reason = rewards(stats)
    if found is None:
        return False, reason
    mean = sum(found) / len(found)
    failed = [r for r in found if r < min_mean]
    n = stats["n_completed_trials"]
    if min_mean >= 1.0 and failed:
        return False, f"reward not perfect (mean={mean:.3f}, rewards={found})"
    if mean < min_mean:
        return False, f"mean reward {mean:.3f} below threshold {min_mean} (rewards={found})"
    return True, f"mean reward {mean:.3f} over {n} trial(s), {len(found)} task(s)"


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
    ok, msg = gate(stats, min_mean)
    print(f"{name}: {msg}", file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
