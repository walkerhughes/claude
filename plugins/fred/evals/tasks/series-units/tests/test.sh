#!/usr/bin/env bash
# Verifier. Two rewards, both computed by rewardkit:
#
#   outcome  the answer is right
#   process  the answer came through the MCP server
#
# `outcome` alone cannot gate this plugin. The mock FRED API is reachable over
# plain HTTP from inside the container, its fixtures sit on disk in plain Python,
# and the real FRED API is reachable over the network. An agent that ignores the
# MCP entirely can still produce the right answer. `process` is what makes these
# MCP evals rather than answer-matching.
rewardkit /tests
