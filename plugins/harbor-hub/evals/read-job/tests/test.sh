#!/bin/bash
# Self-truthing verifier for the read-job eval.
#
# The agent must write the job's mean reward to /app/answer.txt as one decimal.
# With HARBOR_API_KEY threaded in via [verifier.env], the verifier recomputes
# the mean reward from the hub with the harbor CLI and requires the agent's
# answer to match within 1e-6 -- no planted ground-truth constant needed.
set -u

ANSWER_FILE=/app/answer.txt
REWARD_DIR=/logs/verifier
REWARD_FILE="$REWARD_DIR/reward.txt"

mkdir -p "$REWARD_DIR"

fail() {
    echo "FAIL: $1" >&2
    echo 0 > "$REWARD_FILE"
    exit 0
}

pass() {
    echo "PASS: $1"
    echo 1 > "$REWARD_FILE"
    exit 0
}

[ -n "${HARBOR_API_KEY:-}" ] \
    || fail "verifier has no HARBOR_API_KEY (thread it via [verifier.env])"
[ -n "${EVAL_READ_JOB_ID:-}" ] || fail "EVAL_READ_JOB_ID is not set for the verifier"
[ -f "$ANSWER_FILE" ] || fail "answer file $ANSWER_FILE does not exist"

# Trim trailing whitespace/newlines; the answer must be a single non-empty line.
answer="$(tr -d '\r' < "$ANSWER_FILE" | sed -e 's/[[:space:]]*$//' -e '/^$/d')"
[ -n "$answer" ] || fail "answer file $ANSWER_FILE is empty"
[ "$(printf '%s\n' "$answer" | wc -l | tr -d ' ')" -eq 1 ] \
    || fail "answer must be exactly one non-empty line, got: '$answer'"
printf '%s' "$answer" | grep -Eq '^-?[0-9]+(\.[0-9]+)?$' \
    || fail "answer '$answer' is not a plain decimal number"

truth="$(harbor hub job show "$EVAL_READ_JOB_ID" --json 2>/dev/null \
    | python3 -c 'import json, sys; print((json.load(sys.stdin).get("stats") or {})["avg_reward"])' 2>/dev/null)" \
    || fail "could not read job $EVAL_READ_JOB_ID mean reward from the hub"
[ -n "$truth" ] || fail "hub returned no mean reward for job $EVAL_READ_JOB_ID"

awk -v got="$answer" -v want="$truth" \
    'BEGIN { d = got - want; if (d < 0) d = -d; exit !(d <= 1e-6) }' \
    || fail "answer '$answer' does not match hub mean reward '$truth' (job $EVAL_READ_JOB_ID)"

pass "answer '$answer' matches hub mean reward '$truth'"
