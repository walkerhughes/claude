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
# Required:
#   CLAUDE_CODE_OAUTH_TOKEN (preferred) or ANTHROPIC_API_KEY, for the agent
#   docker, running
# Optional:
#   EVAL_ATTEMPTS    trials per task (default 1; job.yaml uses 3 interactively)
#   EVAL_MIN_MEAN    reward threshold (default 1.0, every task must pass)
#   EVALS_OUT_DIR    keep the trials here instead of a temp dir
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HARBOR="${HARBOR:-uv tool run --from harbor==0.13.2 harbor}"
ATTEMPTS="${EVAL_ATTEMPTS:-1}"
MIN_MEAN="${EVAL_MIN_MEAN:-1.0}"

die() { echo "error: $1" >&2; exit 1; }

docker info > /dev/null 2>&1 || die "docker is not running"
if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    die "set CLAUDE_CODE_OAUTH_TOKEN (or ANTHROPIC_API_KEY) for the claude-code agent"
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
# cd into evals/ because harbor resolves the dataset path relative to the
# working directory.
(
    cd "$ROOT/evals"
    # -y auto-confirms harbor's prompts, which would otherwise hang a
    # non-interactive runner rather than fail it.
    $HARBOR run -y -c job.yaml -o "$OUT" --job-name evals-gate --n-attempts "$ATTEMPTS"
)

result="$OUT/evals-gate/result.json"
if ! python3 "$ROOT/evals/check_reward.py" "$result" evals-gate --min-mean "$MIN_MEAN"; then
    echo "--- verifier output ---" >&2
    cat "$OUT/evals-gate"/*/verifier/test-stdout.txt >&2 2>/dev/null || true
    die "the eval gate did not clear $MIN_MEAN"
fi

echo "==> Eval gate passed."
