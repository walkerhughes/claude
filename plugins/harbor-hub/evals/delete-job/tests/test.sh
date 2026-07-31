#!/bin/bash
# Self-truthing verifier for the delete-job eval.
#
# The agent must delete job $EVAL_DELETE_JOB_ID and write "deleted" to /app/answer.txt.
# With HARBOR_API_KEY threaded in via [verifier.env], the verifier confirms via
# the harbor CLI that the job is actually gone from the hub -- claiming success
# without deleting fails. A no-op agent writes nothing and leaves the job, so it
# fails both checks.
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
[ -n "${EVAL_DELETE_JOB_ID:-}" ] || fail "EVAL_DELETE_JOB_ID is not set for the verifier"
[ -f "$ANSWER_FILE" ] || fail "answer file $ANSWER_FILE does not exist"

answer="$(tr -d '\r' < "$ANSWER_FILE" | sed -e 's/[[:space:]]*$//' -e '/^$/d')"
[ "$answer" = "deleted" ] || fail "answer must be exactly 'deleted', got: '$answer'"

# A deleted (or never-existent) job returns an empty object; a live job carries
# a "stats" block. Treat empty/absent as gone.
state="$(harbor hub job show "$EVAL_DELETE_JOB_ID" --json 2>/dev/null \
    | python3 -c 'import json, sys
d = json.load(sys.stdin)
print("gone" if not d or not d.get("stats") else "present")' 2>/dev/null)"
[ "$state" = "gone" ] \
    || fail "job $EVAL_DELETE_JOB_ID is still present on the hub (state='$state')"

pass "job $EVAL_DELETE_JOB_ID was deleted from the hub"
