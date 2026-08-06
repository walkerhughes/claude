#!/usr/bin/env bash
# Runs inside fred-bench, invoked by validate_local.sh. Scores every task's real
# rewardkit verifier against synthetic trajectories and asserts the reward matrix.
#
#   case                answer   trajectory                          outcome  process
#   ------------------  -------  ----------------------------------  -------  -------
#   solved              oracle   called an MCP tool                        1        1
#   empty               none     none                                      0        0
#   bypassed-port       oracle   curled the local mock                     1        0
#   bypassed-fixture    oracle   read the fixtures off disk                1        0
#   bypassed-real       oracle   curled the real FRED API                  1        0
#   delegated           oracle   subagent called an MCP tool               1        1
#   delegated-bypass    oracle   subagent curled the local mock            1        0
#
# The bypass rows are the point, and they are what `harbor run -a oracle` cannot tell
# you. This plugin has three ways round the server rather than tastytrade's two, so
# each gets its own row:
#
#   port     the mock binds every interface, so it answers on localhost, 127.0.0.1,
#            0.0.0.0, [::1] and the container's hostname. This row deliberately uses
#            0.0.0.0, the spelling a hostname list would miss.
#   fixture  every expected answer sits on disk in plain Python. Reading it needs no
#            network at all.
#   real     the benchmark runs with the network up, because the agent needs it to
#            reach its own model, so api.stlouisfed.org is reachable too. tastytrade's
#            mock-only setup never had to consider this one.
#
# The delegated pair covers the blind spot behind all three: harbor's trajectory holds
# the main session only, so a call handed to a subagent shows up as an `Agent` entry
# and no tool. Both halves are asserted together, because crediting a delegated MCP
# call while missing a delegated curl would make "ask a subagent" an invisible bypass.
#
# Expects the repo at /work. Nothing here calls a model or the network.
set -uo pipefail

TASKS=/work/evals/tasks
pass=0
fail=0

mcp_good='{"steps":[{"tool_calls":[{"function_name":"mcp__fred__get_observations","arguments":{"series_ids":"UNRATE"}}]}]}'
bypass_port='{"steps":[{"tool_calls":[{"function_name":"Bash","arguments":{"command":"curl -s http://0.0.0.0:8080/fred/series?series_id=UNRATE"}}]}]}'
bypass_fixture='{"steps":[{"tool_calls":[{"function_name":"Read","arguments":{"file_path":"/opt/fred/tests/fixtures/fred_api.py"}}]}]}'
bypass_real='{"steps":[{"tool_calls":[{"function_name":"Bash","arguments":{"command":"curl -s https://api.stlouisfed.org/fred/series/observations?series_id=UNRATE"}}]}]}'

# What the top-level agent's trajectory looks like when it delegates: an Agent call and
# nothing else. Paired with a subagent transcript below.
delegating='{"steps":[{"tool_calls":[{"function_name":"Agent","arguments":{"description":"Look up the answer"}}]}]}'
# Subagent transcripts are Claude Code session lines, not harbor trajectories:
# type/message.content[] with tool_use blocks carrying `name` and `input`.
sub_mcp='{"type":"assistant","isSidechain":true,"message":{"content":[{"type":"tool_use","id":"t1","name":"mcp__fred__get_observations","input":{"series_ids":"UNRATE"}}]}}'
sub_bypass='{"type":"assistant","isSidechain":true,"message":{"content":[{"type":"tool_use","id":"t1","name":"Bash","input":{"command":"curl -s http://localhost:8080/fred/series"}}]}}'

# Score one task against one trajectory, optionally with a subagent transcript.
# Echoes "<outcome> <process>".
#
# $4 is a Claude Code session line placed where a real subagent's would land, at
# sessions/projects/<proj>/<session>/subagents/. That path is the whole point: harbor's
# session scan skips anything under `subagents/`, so a call written there is absent from
# trajectory.json by construction, exactly as it is in a real delegated run.
score() {
    local task=$1 trajectory=$2 solved=$3 subagent=${4:-}
    local work
    work="$(mktemp -d)"
    mkdir -p "$work/app" "$work/logs/agent" "$work/logs/verifier"

    if [ "$solved" = "yes" ]; then
        APP_DIR="$work/app" bash "$TASKS/$task/solution/solve.sh" > /dev/null 2>&1
    fi
    if [ -n "$trajectory" ]; then
        printf '%s' "$trajectory" > "$work/logs/agent/trajectory.json"
    fi
    if [ -n "$subagent" ]; then
        local subdir="$work/logs/agent/sessions/projects/app/sess/subagents"
        mkdir -p "$subdir"
        printf '%s\n' "$subagent" > "$subdir/sub.jsonl"
    fi

    # rewardkit reads the trajectory from an absolute path baked into the check, so
    # /logs has to be the real one rather than a flag.
    rm -rf /logs && ln -s "$work/logs" /logs
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

    expect "$task" solved           "$(score "$task" "$mcp_good" yes)"        "1.0 1.0"
    expect "$task" empty            "$(score "$task" '' no)"                  "0.0 0.0"
    expect "$task" bypassed-port    "$(score "$task" "$bypass_port" yes)"     "1.0 0.0"
    expect "$task" bypassed-fixture "$(score "$task" "$bypass_fixture" yes)"  "1.0 0.0"
    expect "$task" bypassed-real    "$(score "$task" "$bypass_real" yes)"     "1.0 0.0"
    expect "$task" delegated        "$(score "$task" "$delegating" yes "$sub_mcp")"    "1.0 1.0"
    expect "$task" delegated-bypass "$(score "$task" "$delegating" yes "$sub_bypass")" "1.0 0.0"
done

echo
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
