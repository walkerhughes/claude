#!/usr/bin/env python3
"""Gate a harbor ``result.json`` on its rewards.

Backs the CI reward gates in ``run_evals.sh`` / ``run_eval_safety.sh``:
``harbor run`` returns 0 whatever the reward, so we inspect the job result
ourselves. Rewards are bounded in [0, 1], so on a multi-task run the reported
mean is 1.0 iff every task passed and 0.0 iff every task failed.

    python3 check_reward.py <result.json> <name>                 # all rewards 1
    python3 check_reward.py <result.json> <name> --expect-zero   # all rewards 0
    python3 check_reward.py <result.json> <name> --only outcome  # one reward only
    python3 check_reward.py --selftest

Each eval reports two rewards, ``outcome`` and ``process`` (see evals/README.md).
``--only`` restricts the gate to one of them, which is how the eval-safety check
holds the oracle to ``outcome``: the oracle is a shell script, not an agent, so
it cannot call MCP tools and cannot score on ``process``.
"""

import json
import sys
from pathlib import Path


def _completed_rewards(stats: dict, only: str | None = None) -> tuple[list | None, str]:
    """Rewards list when the run completed cleanly, else (None, reason)."""
    if stats.get("n_errored_trials") or not stats.get("n_completed_trials"):
        return None, f"run did not complete cleanly (stats={stats})"
    # evals -> per-eval stats -> metrics is a list of reward dicts. A task with
    # one reward reports it under the metric name ({"mean": 1.0}); a task with
    # several reports them under the reward names ({"outcome": 1.0, ...}) --
    # see harbor.metrics.base.aggregate_reward_dicts. `only` filters by name.
    rewards = [
        value
        for eval_stats in stats.get("evals", {}).values()
        for metric in eval_stats.get("metrics", [])
        for name, value in metric.items()
        if only is None or name == only
    ]
    if not rewards:
        return None, f"no {only or ''} rewards reported".replace("  ", " ")
    return rewards, ""


def perfect(stats: dict, only: str | None = None) -> tuple[bool, str]:
    """True iff the run completed and every reward is 1."""
    rewards, reason = _completed_rewards(stats, only)
    if rewards is None:
        return False, reason
    if any(reward != 1 for reward in rewards):
        return False, f"reward not perfect (rewards={rewards})"
    return True, f"reward 1.0 over {stats['n_completed_trials']} trial(s)"


def all_zero(stats: dict, only: str | None = None) -> tuple[bool, str]:
    """True iff the run completed and every reward is 0."""
    rewards, reason = _completed_rewards(stats, only)
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
    # Two named rewards: --only gates one dimension. The oracle solves the
    # answer but cannot call MCP tools, so it is outcome=1, process=0.
    split = {
        "n_completed_trials": 1,
        "evals": {"k": {"metrics": [{"outcome": 1.0, "process": 0.0}]}},
    }
    assert not perfect(split)[0]
    assert perfect(split, only="outcome")[0]
    assert not perfect(split, only="process")[0]
    assert all_zero(split, only="process")[0]
    assert not _completed_rewards(split, only="nope")[0]  # unknown name -> None
    print("check_reward selftest ok")


def main(argv: list[str]) -> int:
    if argv[1:2] == ["--selftest"]:
        _selftest()
        return 0
    result_path, name = argv[1], argv[2]
    flags = argv[3:]
    check = all_zero if "--expect-zero" in flags else perfect
    only = flags[flags.index("--only") + 1] if "--only" in flags else None
    try:
        stats = json.loads(Path(result_path).read_text()).get("stats", {})
    except FileNotFoundError:
        print(f"{name}: no result.json at {result_path}", file=sys.stderr)
        return 1
    ok, msg = check(stats, only)
    print(f"{name}: {msg}", file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
