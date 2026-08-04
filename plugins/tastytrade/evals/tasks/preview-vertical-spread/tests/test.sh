#!/usr/bin/env bash
# Verifier. Two rewards, both computed by rewardkit:
#
#   outcome  the answer is right
#   process  the answer came through the MCP server (or, for the skill task, the skill)
#
# `outcome` alone cannot gate this plugin. The mock brokerage is reachable over
# plain HTTP from inside the container and its source is on disk, so an agent
# that ignores the MCP entirely can still produce the right answer. A real run
# did exactly that. `process` is what makes these MCP evals.
rewardkit /tests
