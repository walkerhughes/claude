#!/usr/bin/env bash
# Eval-safety check (backs `make eval-safety`): the oracle must reach reward
# 1.0 on every eval and the nop agent (which produces no answer) must reach
# reward 0 on every eval. This proves each eval is solvable and not trivially
# passable -- run it whenever the evals change. No LLM/Anthropic cost.
#
# Mirrors the gate runner's shape: each agent gets its own pair of freshly
# seeded hub jobs (one to read, one to delete -- no parallel read/delete race),
# then a single `harbor run -p evals/` executes every eval in parallel. All
# seeded jobs are dropped afterwards (the oracle's delete-job removes its own).
#
# Required host environment:
#   HARBOR_API_KEY   Harbor hub API key
# Optional:
#   HARBOR_TEST_ENV  harbor environment provider: docker (default) | modal
#   EVAL_TASK_REF    published task ref for check-published-task
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HARBOR_TEST_ENV="${HARBOR_TEST_ENV:-docker}"
EVAL_TASK_REF="${EVAL_TASK_REF:-hello-world/hello-world@1}"
JOBS_DIR="$(mktemp -d)"

# shellcheck source=evals/_hublib.sh
. "$REPO_ROOT/evals/_hublib.sh"

SEEDED_JOBS=()
cleanup() {
    rm -rf "$JOBS_DIR"
    local job
    for job in "${SEEDED_JOBS[@]:-}"; do
        drop_job "$job"
    done
}
trap cleanup EXIT

die() {
    echo "error: $1" >&2
    exit 1
}

command -v harbor > /dev/null 2>&1 \
    || die "harbor CLI not found on PATH (install with: uv tool install harbor)"
[ -n "${HARBOR_API_KEY:-}" ] \
    || die "HARBOR_API_KEY is not set (mint one with: harbor auth login)"

export HARBOR_API_KEY EVAL_TASK_REF

# run_all <agent>
# Seeds a fresh job pair, then runs every eval in evals/ in parallel with
# <agent>. Leaves the run's result.json at $JOBS_DIR/<agent>/safety-<agent>/.
run_all() {
    local agent=$1
    echo "==> Seeding hub jobs for $agent (env: $HARBOR_TEST_ENV)"
    local read_job delete_job
    read_job="$(bootstrap_job "$JOBS_DIR/$agent-seed-read" "safety-$agent-read")"
    delete_job="$(bootstrap_job "$JOBS_DIR/$agent-seed-delete" "safety-$agent-delete")"
    SEEDED_JOBS+=("$read_job" "$delete_job")
    export EVAL_READ_JOB_ID="$read_job"
    export EVAL_DELETE_JOB_ID="$delete_job"

    echo "==> Running all evals with $agent (env: $HARBOR_TEST_ENV)"
    # -y auto-confirms harbor's prompt for [verifier.env] host vars (it would
    # abort in non-interactive CI otherwise).
    harbor run \
        -y \
        -p "$REPO_ROOT/evals" \
        -a "$agent" \
        -e "$HARBOR_TEST_ENV" \
        -o "$JOBS_DIR/$agent" \
        --job-name "safety-$agent" \
        --ae HARBOR_API_KEY="$HARBOR_API_KEY" \
        --ae EVAL_READ_JOB_ID="$read_job" \
        --ae EVAL_DELETE_JOB_ID="$delete_job" \
        --ae EVAL_TASK_REF="$EVAL_TASK_REF"
}

show_verifier_output() {
    local agent=$1
    echo "--- $agent verifier output ---" >&2
    cat "$JOBS_DIR/$agent/safety-$agent"/*/verifier/test-stdout.txt >&2 2>/dev/null || true
}

# The oracle must solve every eval: the evals are solvable.
run_all oracle
python3 "$REPO_ROOT/evals/check_reward.py" \
    "$JOBS_DIR/oracle/safety-oracle/result.json" safety-oracle \
    || { show_verifier_output oracle; die "the ORACLE did not reach reward 1.0 on every eval (an eval is broken)"; }

# The nop agent must fail every eval: the evals are not trivially passable.
run_all nop
python3 "$REPO_ROOT/evals/check_reward.py" \
    "$JOBS_DIR/nop/safety-nop/result.json" safety-nop --expect-zero \
    || { show_verifier_output nop; die "the NOP agent scored above 0 on an eval (an eval is trivially passable)"; }

echo "==> Eval-safety passed: oracle solved every eval; nop failed every eval."
