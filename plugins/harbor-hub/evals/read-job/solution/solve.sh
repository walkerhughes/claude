#!/bin/bash
# Reference solution (oracle) for the read-job eval.
#
# The eval's real subject is the agent-plus-MCP path; the oracle answers the
# same question independently via the harbor CLI, so a passing oracle proves
# the eval is solvable against the live hub. HARBOR_API_KEY and EVAL_READ_JOB_ID
# reach this script through the agent env (`harbor run --ae`).
set -euo pipefail

mkdir -p /app

harbor hub job show "$EVAL_READ_JOB_ID" --json \
    | python3 -c 'import json, sys; print((json.load(sys.stdin).get("stats") or {})["avg_reward"])' \
    > /app/answer.txt
