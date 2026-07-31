#!/bin/bash
# Self-truthing verifier for the check-published-task eval.
#
# The agent must write "yes" or "no" to /app/answer.txt for whether
# $EVAL_TASK_REF is published. With HARBOR_API_KEY threaded in via
# [verifier.env], the verifier probes the hub with the harbor CLI (a download of
# the ref succeeds iff it is published) and requires the answer to match. A
# no-op agent writes nothing and fails.
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
[ -n "${EVAL_TASK_REF:-}" ] || fail "EVAL_TASK_REF is not set for the verifier"
[ -f "$ANSWER_FILE" ] || fail "answer file $ANSWER_FILE does not exist"

answer="$(tr -d '\r' < "$ANSWER_FILE" | sed -e 's/[[:space:]]*$//' -e '/^$/d')"
printf '%s' "$answer" | grep -Eq '^(yes|no)$' \
    || fail "answer must be exactly 'yes' or 'no', got: '$answer'"

if harbor download "$EVAL_TASK_REF" -o "$(mktemp -d)" > /dev/null 2>&1; then
    truth=yes
else
    truth=no
fi
[ "$answer" = "$truth" ] \
    || fail "answer '$answer' does not match published truth '$truth' for $EVAL_TASK_REF"

pass "answer '$answer' matches published truth '$truth' for $EVAL_TASK_REF"
