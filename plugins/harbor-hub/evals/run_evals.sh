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
# Repo-wide convention: ci-evals-<plugin>, so every plugin's CI runs are
# searchable together on the hub instead of hiding behind a generic name.
JOB_NAME="ci-evals-harbor-hub"
EVAL_TASK_REF="${EVAL_TASK_REF:-hello-world/hello-world@1}"
# Git ref the eval images pip-install harbor-mcp from. The default branch is
# only right for a run of main: as a PR gate the images must be built from the
# code under review, or the gate greenlights a broken server because it tested
# main's. CI passes the PR head sha.
HARBOR_MCP_REF="${HARBOR_MCP_REF:-main}"
# Where the run's trials land. Defaults to a temp dir that is deleted on exit;
# set EVALS_OUT_DIR to keep them. A `process` failure is only diagnosable from
# the agent's trajectory, so throwing the trials away leaves you with a bare
# 0.0 and no way to tell a wrong tool name from a real CLI shortcut. CI sets
# this and uploads the tree when the gate fails.
JOBS_DIR="${EVALS_OUT_DIR:-}"
if [ -n "$JOBS_DIR" ]; then
    mkdir -p "$JOBS_DIR"
    KEEP_JOBS_DIR=1
else
    JOBS_DIR="$(mktemp -d)"
    KEEP_JOBS_DIR=0
fi

# shellcheck source=evals/_hublib.sh
. "$REPO_ROOT/evals/_hublib.sh"

READ_JOB_ID=""
DELETE_JOB_ID=""
cleanup() {
    [ "$KEEP_JOBS_DIR" -eq 1 ] || rm -rf "$JOBS_DIR"
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

# Pin the images to HARBOR_MCP_REF in a throwaway copy of the tree rather than
# rewriting the checkout: an interrupted run must not leave a pinned Dockerfile
# behind for the next one to build from.
EVALS_SRC="$JOBS_DIR/evals-src"
cp -R "$REPO_ROOT/evals" "$EVALS_SRC"
pinned=0
while IFS= read -r dockerfile; do
    sed -i.bak \
        "s|claude\.git#subdirectory|claude.git@${HARBOR_MCP_REF}#subdirectory|" \
        "$dockerfile"
    rm -f "$dockerfile.bak"
    pinned=$((pinned + 1))
done < <(grep -rl 'claude\.git#subdirectory' "$EVALS_SRC")
[ "$pinned" -gt 0 ] \
    || die "no eval Dockerfile pinned to $HARBOR_MCP_REF; the install line moved"
echo "==> Eval images will build harbor-mcp from $HARBOR_MCP_REF ($pinned Dockerfiles)"

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
run_args=(
    -y
    -p "$EVALS_SRC"
    -a claude-code
    -e "$HARBOR_TEST_ENV"
    -o "$JOBS_DIR"
    --job-name "$JOB_NAME"
    --ae HARBOR_API_KEY="$HARBOR_API_KEY"
    --ae EVAL_READ_JOB_ID="$READ_JOB_ID"
    --ae EVAL_DELETE_JOB_ID="$DELETE_JOB_ID"
    --ae EVAL_TASK_REF="$EVAL_TASK_REF"
)
# Off by default, and off for PR runs: a job per push would pile up, and unlike
# the seeds nothing drops these -- persisting them is the point. CI sets it on
# pushes to main, so the hub keeps the reward/cost/token trend for the branch
# that ships. Uploaded jobs are private by default; the trajectories contain
# the eval instructions and the agent's full reasoning.
if [ -n "${EVALS_UPLOAD:-}" ]; then
    echo "==> Results will be uploaded to the Harbor hub"
    run_args+=(--upload)
fi

harbor run "${run_args[@]}"

# harbor run exits 0 regardless of reward; gate on a perfect result so CI
# (and `make evals`) fails the moment any eval regresses.
if ! python3 "$REPO_ROOT/evals/check_reward.py" "$JOBS_DIR/$JOB_NAME/result.json" "$JOB_NAME"; then
    echo "--- verifier output ---" >&2
    cat "$JOBS_DIR/$JOB_NAME"/*/verifier/test-stdout.txt >&2 2>/dev/null || true
    die "the evals did not all reach reward 1.0"
fi

echo "==> All evals passed with reward 1.0."
