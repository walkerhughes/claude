#!/usr/bin/env bash
# Gate runner (backs `make evals`): drives the harbor-mcp hub-capability evals
# with the claude-code agent and fails unless every eval reaches reward 1.0.
# It proves the MCP's basic hub operations work for a real agent:
#
#   read-job              read a job's mean reward   (job reads)
#   delete-job            delete a job (writes gate) (job writes)
#   check-published-task  is a task published?       (registry reads)
#
# Three phases:
#   1. SEED: mint two fresh hub jobs with the oracle (no LLM cost) -- one for
#      read-job, one for delete-job. Separate jobs let the evals run in
#      parallel with no read/delete race.
#   2. RUN: a single `harbor run -p evals/` executes every task directory in
#      evals/ in parallel with claude-code. Per-eval inputs are the
#      EVAL_READ_JOB_ID / EVAL_DELETE_JOB_ID / EVAL_TASK_REF env vars;
#      delete-job enables MCP writes for itself via its own [environment.env].
#   3. CLEANUP: drop any seeded job that still exists (delete-job removes its
#      own on success; the read job always needs dropping).
#
# Verifiers are self-truthing: they recompute ground truth from the hub via the
# harbor CLI (HARBOR_API_KEY threaded through each task's [verifier.env]).
#
# Required host environment:
#   HARBOR_API_KEY   Harbor hub API key (mint with `harbor auth login`)
#   ANTHROPIC_API_KEY (or CLAUDE_CODE_OAUTH_TOKEN) for the claude-code agent
# Optional:
#   HARBOR_TEST_ENV  harbor environment provider: docker (default) | modal
#   EVAL_TASK_REF    published task ref for check-published-task
#                    (default: hello-world/hello-world@1, an immutable public task)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HARBOR_TEST_ENV="${HARBOR_TEST_ENV:-docker}"
EVAL_TASK_REF="${EVAL_TASK_REF:-hello-world/hello-world@1}"
JOBS_DIR="$(mktemp -d)"

# shellcheck source=evals/_hublib.sh
. "$REPO_ROOT/evals/_hublib.sh"

READ_JOB_ID=""
DELETE_JOB_ID=""
cleanup() {
    rm -rf "$JOBS_DIR"
    drop_job "$READ_JOB_ID"
    drop_job "$DELETE_JOB_ID"
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
if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
    echo "warning: neither ANTHROPIC_API_KEY nor CLAUDE_CODE_OAUTH_TOKEN is set;" \
        "the claude-code agent will likely fail to authenticate" >&2
fi

echo "==> Seeding hub jobs (oracle, env: $HARBOR_TEST_ENV)"
READ_JOB_ID="$(bootstrap_job "$JOBS_DIR/seed-read" harbor-mcp-eval-read)"
DELETE_JOB_ID="$(bootstrap_job "$JOBS_DIR/seed-delete" harbor-mcp-eval-delete)"
echo "==> Seeded read job $READ_JOB_ID and delete job $DELETE_JOB_ID"

# Exported so harbor resolves them into each task's [verifier.env] templates;
# passed with --ae so the agent (and its MCP server) sees them too.
export HARBOR_API_KEY EVAL_TASK_REF
export EVAL_READ_JOB_ID="$READ_JOB_ID"
export EVAL_DELETE_JOB_ID="$DELETE_JOB_ID"

echo "==> Running all evals in parallel (claude-code, env: $HARBOR_TEST_ENV)"
# -y auto-confirms harbor's prompt for [verifier.env] host vars (it would
# abort in non-interactive CI otherwise).
harbor run \
    -y \
    -p "$REPO_ROOT/evals" \
    -a claude-code \
    -e "$HARBOR_TEST_ENV" \
    -o "$JOBS_DIR" \
    --job-name evals-gate \
    --ae HARBOR_API_KEY="$HARBOR_API_KEY" \
    --ae EVAL_READ_JOB_ID="$READ_JOB_ID" \
    --ae EVAL_DELETE_JOB_ID="$DELETE_JOB_ID" \
    --ae EVAL_TASK_REF="$EVAL_TASK_REF"

# harbor run exits 0 regardless of reward; gate on a perfect result so CI
# (and `make evals`) fails the moment any eval regresses.
if ! python3 "$REPO_ROOT/evals/check_reward.py" "$JOBS_DIR/evals-gate/result.json" evals-gate; then
    echo "--- verifier output ---" >&2
    cat "$JOBS_DIR/evals-gate"/*/verifier/test-stdout.txt >&2 2>/dev/null || true
    die "the evals did not all reach reward 1.0"
fi

echo "==> All evals passed with reward 1.0."
