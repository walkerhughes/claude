#!/usr/bin/env python3
"""Gate a harbor ``result.json`` on its rewards.

Backs the CI reward gates in ``run_evals.sh`` / ``run_eval_safety.sh``:
``harbor run`` returns 0 whatever the reward, so we inspect the job result
ourselves. Rewards are bounded in [0, 1], so on a multi-task run the reported
mean is 1.0 iff every task passed and 0.0 iff every task failed.

    python3 check_reward.py <result.json> <name>                # all rewards 1
    python3 check_reward.py <result.json> <name> --expect-zero  # all rewards 0
    python3 check_reward.py --selftest
"""

import json
import sys
from pathlib import Path


def _completed_rewards(stats: dict) -> tuple[list | None, str]:
    """Rewards list when the run completed cleanly, else (None, reason)."""
    if stats.get("n_errored_trials") or not stats.get("n_completed_trials"):
        return None, f"run did not complete cleanly (stats={stats})"
    # evals -> per-eval stats -> metrics is a list of single-key reward dicts
    # (e.g. [{"mean": 1.0}]).
    rewards = [
        value
        for eval_stats in stats.get("evals", {}).values()
        for metric in eval_stats.get("metrics", [])
        for value in metric.values()
    ]
    if not rewards:
        return None, "no rewards reported"
    return rewards, ""


def perfect(stats: dict) -> tuple[bool, str]:
    """True iff the run completed and every reward is 1."""
    rewards, reason = _completed_rewards(stats)
    if rewards is None:
        return False, reason
    if any(reward != 1 for reward in rewards):
        return False, f"reward not perfect (rewards={rewards})"
    return True, f"reward 1.0 over {stats['n_completed_trials']} trial(s)"


def all_zero(stats: dict) -> tuple[bool, str]:
    """True iff the run completed and every reward is 0."""
    rewards, reason = _completed_rewards(stats)
    if rewards is None:
        return False, reason
    if any(reward != 0 for reward in rewards):
        return False, f"expected all-zero rewards (rewards={rewards})"
    return True, f"reward 0.0 over {stats['n_completed_trials']} trial(s)"


def _selftest() -> None:
    ok = {"n_completed_trials": 1, "evals": {"k": {"metrics": [{"mean": 1.0}]}}}
    assert perfect(ok)[0]
    assert not perfect({**ok, "evals": {"k": {"metrics": [{"mean": 0.0}]}}})[0]
    assert not perfect({**ok, "n_errored_trials": 1})[0]
    assert not perfect({"n_completed_trials": 0, "evals": {}})[0]
    assert not perfect({"n_completed_trials": 1, "evals": {}})[0]  # no rewards
    zero = {"n_completed_trials": 3, "evals": {"k": {"metrics": [{"mean": 0.0}]}}}
    assert all_zero(zero)[0]
    assert not all_zero(ok)[0]
    assert not all_zero({**zero, "evals": {"k": {"metrics": [{"mean": 0.5}]}}})[0]
    assert not all_zero({**zero, "n_errored_trials": 1})[0]
    print("check_reward selftest ok")


def main(argv: list[str]) -> int:
    if argv[1:2] == ["--selftest"]:
        _selftest()
        return 0
    result_path, name = argv[1], argv[2]
    check = all_zero if "--expect-zero" in argv[3:] else perfect
    try:
        stats = json.loads(Path(result_path).read_text()).get("stats", {})
    except FileNotFoundError:
        print(f"{name}: no result.json at {result_path}", file=sys.stderr)
        return 1
    ok, msg = check(stats)
    print(f"{name}: {msg}", file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
