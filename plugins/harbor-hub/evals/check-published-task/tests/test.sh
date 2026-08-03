#!/bin/bash
# Verifier for the check-published-task eval. Two rewards, both computed by rewardkit
# (baked into the image by environment/Dockerfile):
#
#   outcome  the answer matches the published truth probed live from the hub
#   process  the answer was obtained through the harbor-hub MCP server
#
# `outcome` alone cannot gate the MCP: the harbor CLI is on PATH for the oracle
# and the verifier, so an agent that ignores the MCP and shells out still gets
# the right number. `process` is what makes this an MCP eval.
rewardkit /tests
