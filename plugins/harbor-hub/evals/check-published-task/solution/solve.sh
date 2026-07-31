#!/bin/bash
# Reference solution (oracle) for the check-published-task eval.
#
# The eval's real subject is the agent-plus-MCP path; the oracle answers the
# same question independently via the harbor CLI (a download of the ref
# succeeds iff it is published), so a passing oracle proves the eval is solvable
# against the live hub. HARBOR_API_KEY and EVAL_TASK_REF reach this script
# through the agent env (`harbor run --ae`).
set -euo pipefail

mkdir -p /app

if harbor download "$EVAL_TASK_REF" -o "$(mktemp -d)" > /dev/null 2>&1; then
    echo yes > /app/answer.txt
else
    echo no > /app/answer.txt
fi
