#!/usr/bin/env bash
# Validate every task's verifier WITHOUT Harbor or Docker: run the oracle (solve.sh),
# then the verifier (test.sh), and confirm it awards reward 1. Then corrupt the answer and
# confirm the verifier awards 0. This is the local stand-in for `harbor run -a oracle`.
set -euo pipefail
cd "$(dirname "$0")/tasks"

pass=0
fail=0
for task in */; do
  task="${task%/}"
  [ -f "$task/tests/test.sh" ] || continue
  work="$(mktemp -d)"
  export APP_DIR="$work/app"
  export LOG_DIR="$work/logs"
  export MOCK_STATE_FILE="$APP_DIR/placed_orders.jsonl"
  mkdir -p "$APP_DIR" "$LOG_DIR"

  # Captured rather than discarded: on failure these logs are the only clue, and
  # a CI run that prints just a task name means reproducing it locally to learn
  # anything. Kept inside $work so they are cleaned up with it.
  bash "$task/solution/solve.sh" >"$work/oracle.log" 2>&1 || true
  bash "$task/tests/test.sh" >"$work/verify.log" 2>&1 || true
  reward="$(cat "$LOG_DIR/reward.txt" 2>/dev/null || echo missing)"

  # Negative control: an empty answer must NOT earn reward.
  rm -rf "$APP_DIR"/* "$LOG_DIR"/* 2>/dev/null || true
  echo '{}' > "$APP_DIR/answer.json"
  bash "$task/tests/test.sh" >"$work/negative.log" 2>&1 || true
  neg="$(cat "$LOG_DIR/reward.txt" 2>/dev/null || echo missing)"

  if [ "$reward" = "1" ] && [ "$neg" = "0" ]; then
    echo "PASS  $task"
    pass=$((pass + 1))
  else
    echo "FAIL  $task  (oracle=$reward negative=$neg)"
    for log in oracle verify negative; do
      if [ -s "$work/$log.log" ]; then
        echo "      --- $log ---"
        sed 's/^/      /' "$work/$log.log" | tail -15
      fi
    done
    fail=$((fail + 1))
  fi
  rm -rf "$work"
done

echo
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
