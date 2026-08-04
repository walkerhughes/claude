#!/usr/bin/env bash
# Runs inside tastytrade-bench, invoked by validate_local.sh. Scores every task's
# real rewardkit verifier against three synthetic trajectories and asserts the
# reward matrix.
#
#   case          answer      trajectory                    outcome  process
#   ------------  ----------  ----------------------------  -------  -------
#   solved        oracle      took the intended route             1        1
#   empty         none        none                                0        0
#   bypassed      oracle      went round the server               1        0
#   bypassed-alt  oracle      went round it another way           1        0
#
# The last two rows are the point. Before the split, "bypassed" scored a clean
# 1.0 and a real gate run did exactly that: right answer, server never touched.
#
# "bypassed-alt" exists because one spelling of a bypass proves only that one
# spelling is caught. The mock binds every interface, so it answers on more
# addresses than a host-matching check can enumerate, and hand arithmetic on the
# chain leaves no distinctive string at all.
#
# Expects the repo at /work. Nothing here calls a model or the network.
set -uo pipefail

TASKS=/work/evals/tasks
pass=0
fail=0

# The intended route differs by task, so the trajectories do too. Skill tasks are
# detected from their own process check rather than by name, so adding another
# skill task needs no edit here.
mcp_good='{"steps":[{"tool_calls":[{"function_name":"mcp__tastytrade__get_portfolio","arguments":{}}]}]}'
mcp_bypass='{"steps":[{"tool_calls":[{"function_name":"Bash","arguments":{"command":"curl -s http://localhost:8080/customers/me/accounts"}}]}]}'
# The same bypass through an address the old host-list did not name. The mock
# binds 0.0.0.0, so this reaches it just as well as localhost does.
mcp_bypass_alt='{"steps":[{"tool_calls":[{"function_name":"Bash","arguments":{"command":"curl -s http://0.0.0.0:8080/customers/me/accounts"}}]}]}'
skill_good='{"steps":[{"tool_calls":[{"function_name":"Bash","arguments":{"command":"python3 /opt/tastytrade/scripts/calendars.py fit chain.json"}}]}]}'
skill_bypass='{"steps":[{"tool_calls":[{"function_name":"Read","arguments":{"file_path":"/opt/tastytrade/skills/earnings-calendars/reference/pltr-2026-08-03.json"}}]}]}'
# Eyeballing the straddle: no skill, no script, and nothing to pattern-match on
# but the absence of the intended route. This is the run that scored 1.0 before
# the split existed.
skill_bypass_alt='{"steps":[{"tool_calls":[{"function_name":"Bash","arguments":{"command":"python3 -c \"print((2.34 + 2.62) / 125.64 * 100)\""}}]}]}'

# Score one task against one trajectory. Echoes "<outcome> <process>".
score() {
    local task=$1 trajectory=$2 solved=$3
    local work
    work="$(mktemp -d)"
    mkdir -p "$work/app" "$work/logs/agent" "$work/logs/verifier"

    if [ "$solved" = "yes" ]; then
        APP_DIR="$work/app" MOCK_STATE_FILE="$work/app/placed_orders.jsonl" \
            bash "$TASKS/$task/solution/solve.sh" > /dev/null 2>&1
    fi
    if [ -n "$trajectory" ]; then
        printf '%s' "$trajectory" > "$work/logs/agent/trajectory.json"
    fi

    # rewardkit reads the trajectory from an absolute path baked into the check,
    # so /logs has to be the real one rather than a flag.
    rm -rf /logs && ln -s "$work/logs" /logs
    MOCK_STATE_FILE="$work/app/placed_orders.jsonl" \
        rewardkit "$TASKS/$task/tests" --workspace "$work/app" \
        --output "$work/logs/verifier/reward.json" > /dev/null 2>&1

    python3 - "$work/logs/verifier/reward.json" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    print("err err"); raise SystemExit
print(f"{d.get('outcome', 'missing')} {d.get('process', 'missing')}")
PY
    rm -rf "$work"
}

expect() {
    local task=$1 case_name=$2 got=$3 want=$4
    if [ "$got" = "$want" ]; then
        pass=$((pass + 1))
    else
        fail=$((fail + 1))
        echo "FAIL  $task [$case_name]: expected (outcome process) = ($want), got ($got)"
    fi
}

for dir in "$TASKS"/*/; do
    task="$(basename "$dir")"
    [ -f "$dir/tests/test.sh" ] || continue

    if grep -q "earnings-calendars" "$dir/tests/process/check.py" 2> /dev/null; then
        good=$skill_good
        bypass=$skill_bypass
        bypass_alt=$skill_bypass_alt
    else
        good=$mcp_good
        bypass=$mcp_bypass
        bypass_alt=$mcp_bypass_alt
    fi

    expect "$task" solved       "$(score "$task" "$good" yes)"       "1.0 1.0"
    expect "$task" empty        "$(score "$task" '' no)"             "0.0 0.0"
    expect "$task" bypassed     "$(score "$task" "$bypass" yes)"     "1.0 0.0"
    expect "$task" bypassed-alt "$(score "$task" "$bypass_alt" yes)" "1.0 0.0"
done

echo
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
