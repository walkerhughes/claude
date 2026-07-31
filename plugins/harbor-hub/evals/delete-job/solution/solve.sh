#!/bin/bash
# Reference solution (oracle) for the delete-job eval.
#
# The eval's real subject is the agent-plus-MCP path; the oracle performs the
# same delete independently via the harbor CLI, so a passing oracle proves the
# eval is solvable against the live hub. HARBOR_API_KEY and EVAL_DELETE_JOB_ID reach
# this script through the agent env (`harbor run --ae`).
set -euo pipefail

mkdir -p /app

harbor hub job delete "$EVAL_DELETE_JOB_ID" -y
echo deleted > /app/answer.txt
