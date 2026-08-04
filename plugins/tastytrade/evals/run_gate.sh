#!/usr/bin/env bash
# Gate runner (backs `make evals`): drives the eval tasks with the claude-code
# agent against the mock Tastytrade API, and fails unless the rewards clear a
# threshold. This is the merge gate on the tool surface and on the
# earnings-calendars skill.
#
# `make validate-tasks` is the other half and a different question: it checks
# that each verifier accepts its oracle and rejects an empty answer, with no
# model involved. That catches a broken verifier. Only this catches a server or
# skill that a real agent cannot drive.
#
# Hub results are named `ci-evals-tastytrade`. That is the repo-wide convention,
# `ci-evals-<plugin>`, so every plugin's CI runs are searchable together on the
# hub and no plugin's history hides behind a generic name.
#
# Required:
#   CLAUDE_CODE_OAUTH_TOKEN   subscription auth for the agent
#   docker, running
# Optional:
#   EVAL_ATTEMPTS    trials per task (default 1; job.yaml uses 3 interactively)
#   EVAL_MIN_MEAN    reward threshold (default 1.0, every task must pass)
#   EVALS_OUT_DIR    keep the trials here instead of a temp dir
#   EVALS_UPLOAD     set to push results to the Harbor hub (needs HARBOR_API_KEY)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HARBOR="${HARBOR:-uv tool run --from harbor==0.18.0 harbor}"
ATTEMPTS="${EVAL_ATTEMPTS:-1}"
MIN_MEAN="${EVAL_MIN_MEAN:-1.0}"
JOB_NAME="ci-evals-tastytrade"

die() { echo "error: $1" >&2; exit 1; }

docker info > /dev/null 2>&1 || die "docker is not running"
# Subscription auth only. An ANTHROPIC_API_KEY in the environment would be
# preferred by the CLI over the token and quietly move the run onto credits, so
# it is not accepted as a fallback here.
[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] \
    || die "CLAUDE_CODE_OAUTH_TOKEN is not set (mint one with: claude setup-token)"
if [ -n "${EVALS_UPLOAD:-}" ] && [ -z "${HARBOR_API_KEY:-}" ]; then
    die "EVALS_UPLOAD is set but HARBOR_API_KEY is not (mint one with: harbor auth login)"
fi

# Trials are the only way to diagnose a failure: a bare 0.0 cannot distinguish
# a server bug from an agent that misread the prompt. CI sets EVALS_OUT_DIR and
# uploads the tree.
OUT="${EVALS_OUT_DIR:-}"
if [ -n "$OUT" ]; then
    mkdir -p "$OUT"; KEEP=1
else
    OUT="$(mktemp -d)"; KEEP=0
fi
cleanup() { [ "$KEEP" -eq 1 ] || rm -rf "$OUT"; }
trap cleanup EXIT

# Built from the working tree, so the gate measures the code under review. A
# stale image would pass a PR that breaks the server.
echo "==> Building tastytrade-bench from the working tree"
( cd "$ROOT" && docker build -q -f evals/environment/Dockerfile -t tastytrade-bench . )

echo "==> Running $ATTEMPTS attempt(s) per task with claude-code"
# -y auto-confirms harbor's prompts, which would otherwise hang a
# non-interactive runner rather than fail it.
run_args=(--yes --config job.yaml --jobs-dir "$OUT" --job-name "$JOB_NAME" --n-attempts "$ATTEMPTS")
# Off for PR runs: a hub job per push would pile up with nothing to clean them
# up. CI sets it on pushes to main, where keeping the reward/cost/token trend
# for the branch that ships is the point. Uploaded jobs are private by default,
# and the trajectories contain the task instructions and the agent's reasoning.
if [ -n "${EVALS_UPLOAD:-}" ]; then
    echo "==> Results will be uploaded to the Harbor hub as $JOB_NAME"
    run_args+=(--upload)
fi

# cd into evals/ because harbor resolves the dataset path relative to the
# working directory.
( cd "$ROOT/evals" && $HARBOR run "${run_args[@]}" )

result="$OUT/$JOB_NAME/result.json"
if ! python3 "$ROOT/evals/check_reward.py" "$result" "$JOB_NAME" --min-mean "$MIN_MEAN"; then
    echo "--- verifier output ---" >&2
    cat "$OUT/$JOB_NAME"/*/verifier/test-stdout.txt >&2 2>/dev/null || true
    die "the eval gate did not clear $MIN_MEAN"
fi

echo "==> Eval gate passed."
